"""Field-app service layer (Phase 12): job attachments and time-clock entries.

Both mutation paths are designed to be safely replayable by the frontend's
offline-sync queue: a caller-supplied `idempotency_key` is stored on the row,
and a repeat call with the same key returns the original row instead of
inserting/transitioning a second time (see README, "Offline queue
idempotency"). Everything else follows the same tenant-scoped,
`tenant_context`-armed, raw-SQL discipline as `app.services.jobs`.

Marine threat model Scenario 3 (2026-08-11) additions:
  - Optional `client_queued_at` is age-checked (hard reject past max age;
    structured warn above the warn threshold).
  - Idempotency-key hits are structured-logged so silent replays are auditable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, ValidationFailed

logger = structlog.get_logger(__name__)


def _require_job(db: Session, job_id: uuid.UUID) -> None:
    found = db.execute(text("SELECT 1 FROM jobs WHERE id = :id"), {"id": job_id}).first()
    if found is None:
        raise NotFound(f"job {job_id} not found")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def check_client_queued_at(
    client_queued_at: datetime | None,
    *,
    action: str,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> None:
    """Validate optional offline-queue enqueue timestamp (Scenario 3).

    - Missing timestamp: allowed (online clients / older app builds).
    - Far future: rejected (clock skew / tampering).
    - Older than hard max: rejected (stale fraudulent injection defense).
    - Older than warn threshold: accepted + structured warning.
    """
    if client_queued_at is None:
        return

    now = datetime.now(timezone.utc)
    queued = _as_utc(client_queued_at)
    age_seconds = (now - queued).total_seconds()
    future_skew = settings.offline_queue_future_skew_seconds

    if age_seconds < -future_skew:
        logger.warning(
            "offline_queue_client_queued_at_future",
            action=action,
            company_id=str(company_id),
            job_id=str(job_id),
            user_id=str(user_id) if user_id else None,
            idempotency_key=idempotency_key,
            age_seconds=age_seconds,
        )
        raise ValidationFailed(
            "client_queued_at is too far in the future "
            f"(allowed skew {future_skew}s)"
        )

    if age_seconds > settings.offline_queue_max_age_seconds:
        logger.warning(
            "offline_queue_client_queued_at_too_old",
            action=action,
            company_id=str(company_id),
            job_id=str(job_id),
            user_id=str(user_id) if user_id else None,
            idempotency_key=idempotency_key,
            age_seconds=age_seconds,
            max_age_seconds=settings.offline_queue_max_age_seconds,
        )
        raise ValidationFailed(
            "offline action is too old to replay "
            f"(max age {settings.offline_queue_max_age_seconds}s)"
        )

    if age_seconds > settings.offline_queue_warn_age_seconds:
        logger.warning(
            "offline_queue_client_queued_at_stale",
            action=action,
            company_id=str(company_id),
            job_id=str(job_id),
            user_id=str(user_id) if user_id else None,
            idempotency_key=idempotency_key,
            age_seconds=age_seconds,
            warn_age_seconds=settings.offline_queue_warn_age_seconds,
        )


def _log_idempotency_replay(
    *,
    action: str,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    idempotency_key: str,
    user_id: uuid.UUID | None = None,
    row_id: Any = None,
) -> None:
    """Structured audit line when an offline idempotency key hits an existing row."""
    logger.info(
        "offline_queue_idempotency_replay",
        action=action,
        company_id=str(company_id),
        job_id=str(job_id),
        user_id=str(user_id) if user_id else None,
        idempotency_key=idempotency_key,
        existing_row_id=str(row_id) if row_id is not None else None,
    )


# ---------------------------------------------------------------------------
# attachments — photos and digital signatures
# ---------------------------------------------------------------------------
def add_attachment(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    data: dict[str, Any],
) -> Row:
    """Attach a photo or signature to a job.

    If `idempotency_key` is set and a row with that key already exists for
    this job, the existing row is returned unchanged (idempotent replay) —
    the offline queue may resend the same "upload this photo" action after a
    dropped response without creating a duplicate attachment.
    """
    idempotency_key = data.get("idempotency_key")
    client_queued_at = data.get("client_queued_at")
    check_client_queued_at(
        client_queued_at,
        action="attachment",
        company_id=company_id,
        job_id=job_id,
        user_id=uploaded_by,
        idempotency_key=idempotency_key,
    )

    with tenant_context(db, company_id):
        _require_job(db, job_id)

        if idempotency_key is not None:
            existing = db.execute(
                text(
                    """
                    SELECT * FROM job_attachments
                     WHERE company_id = :cid AND idempotency_key = :key
                    """
                ),
                {"cid": company_id, "key": idempotency_key},
            ).first()
            if existing is not None:
                _log_idempotency_replay(
                    action="attachment",
                    company_id=company_id,
                    job_id=job_id,
                    user_id=uploaded_by,
                    idempotency_key=idempotency_key,
                    row_id=getattr(existing, "id", None),
                )
                return existing

        try:
            row = db.execute(
                text(
                    """
                    INSERT INTO job_attachments
                        (company_id, job_id, kind, data, content_type,
                         idempotency_key, uploaded_by)
                    VALUES
                        (:company_id, :job_id, CAST(:kind AS job_attachment_kind),
                         :data, :content_type, :idempotency_key, :uploaded_by)
                    RETURNING *
                    """
                ),
                {
                    "company_id": company_id,
                    "job_id": job_id,
                    "kind": data["kind"],
                    "data": data["data"],
                    "content_type": data.get("content_type", "image/jpeg"),
                    "idempotency_key": idempotency_key,
                    "uploaded_by": uploaded_by,
                },
            ).first()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # A concurrent duplicate replay lost the race above; fetch and
            # return the winning row rather than surfacing a 500/409 for a
            # request that is, semantically, "already done".
            if idempotency_key is not None:
                existing = db.execute(
                    text(
                        """
                        SELECT * FROM job_attachments
                         WHERE company_id = :cid AND idempotency_key = :key
                        """
                    ),
                    {"cid": company_id, "key": idempotency_key},
                ).first()
                if existing is not None:
                    _log_idempotency_replay(
                        action="attachment",
                        company_id=company_id,
                        job_id=job_id,
                        user_id=uploaded_by,
                        idempotency_key=idempotency_key,
                        row_id=getattr(existing, "id", None),
                    )
                    return existing
            raise Conflict("attachment violates a database constraint") from exc
    return row


def list_attachments(db: Session, company_id: uuid.UUID, job_id: uuid.UUID) -> list[Row]:
    with tenant_context(db, company_id):
        _require_job(db, job_id)
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM job_attachments
                     WHERE job_id = :job_id
                     ORDER BY created_at
                    """
                ),
                {"job_id": job_id},
            ).all()
        )


# ---------------------------------------------------------------------------
# time clock
# ---------------------------------------------------------------------------
def clock_in(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    technician_id: uuid.UUID,
    idempotency_key: str | None = None,
    client_queued_at: datetime | None = None,
) -> Row:
    """Open a time entry for `technician_id` on `job_id`.

    Refuses a second concurrent clock-in for the same (job, technician) pair
    (`uq_job_time_entries_one_open_per_tech_job`) — the technician must clock
    out first. An idempotent replay of the SAME clock-in (matching key)
    returns the entry it already created instead of a 409.
    """
    check_client_queued_at(
        client_queued_at,
        action="clock_in",
        company_id=company_id,
        job_id=job_id,
        user_id=technician_id,
        idempotency_key=idempotency_key,
    )

    with tenant_context(db, company_id):
        _require_job(db, job_id)

        if idempotency_key is not None:
            existing = db.execute(
                text(
                    """
                    SELECT * FROM job_time_entries
                     WHERE company_id = :cid AND idempotency_key = :key
                    """
                ),
                {"cid": company_id, "key": idempotency_key},
            ).first()
            if existing is not None:
                _log_idempotency_replay(
                    action="clock_in",
                    company_id=company_id,
                    job_id=job_id,
                    user_id=technician_id,
                    idempotency_key=idempotency_key,
                    row_id=getattr(existing, "id", None),
                )
                return existing

        try:
            row = db.execute(
                text(
                    """
                    INSERT INTO job_time_entries
                        (company_id, job_id, technician_id, idempotency_key)
                    VALUES (:cid, :job_id, :tech, :key)
                    RETURNING *
                    """
                ),
                {
                    "cid": company_id,
                    "job_id": job_id,
                    "tech": technician_id,
                    "key": idempotency_key,
                },
            ).first()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            detail = str(exc.orig)
            if "uq_job_time_entries_idempotency" in detail and idempotency_key is not None:
                existing = db.execute(
                    text(
                        """
                        SELECT * FROM job_time_entries
                         WHERE company_id = :cid AND idempotency_key = :key
                        """
                    ),
                    {"cid": company_id, "key": idempotency_key},
                ).first()
                if existing is not None:
                    _log_idempotency_replay(
                        action="clock_in",
                        company_id=company_id,
                        job_id=job_id,
                        user_id=technician_id,
                        idempotency_key=idempotency_key,
                        row_id=getattr(existing, "id", None),
                    )
                    return existing
            if "uq_job_time_entries_one_open_per_tech_job" in detail:
                raise Conflict(
                    "technician is already clocked in on this job"
                ) from exc
            raise Conflict("time entry violates a database constraint") from exc
    return row


def clock_out(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    technician_id: uuid.UUID,
    idempotency_key: str | None = None,
    client_queued_at: datetime | None = None,
) -> Row:
    """Close the technician's open time entry on this job.

    `ValidationFailed` if there is no open entry to close. An idempotent
    replay (matching key, entry already closed) returns the closed row
    rather than erroring — closing an already-closed entry a second time via
    the offline queue must be a no-op, not a failure.
    """
    check_client_queued_at(
        client_queued_at,
        action="clock_out",
        company_id=company_id,
        job_id=job_id,
        user_id=technician_id,
        idempotency_key=idempotency_key,
    )

    with tenant_context(db, company_id):
        _require_job(db, job_id)

        if idempotency_key is not None:
            existing = db.execute(
                text(
                    """
                    SELECT * FROM job_time_entries
                     WHERE company_id = :cid AND idempotency_key = :key
                    """
                ),
                {"cid": company_id, "key": idempotency_key},
            ).first()
            if existing is not None:
                _log_idempotency_replay(
                    action="clock_out",
                    company_id=company_id,
                    job_id=job_id,
                    user_id=technician_id,
                    idempotency_key=idempotency_key,
                    row_id=getattr(existing, "id", None),
                )
                return existing

        open_entry = db.execute(
            text(
                """
                SELECT id FROM job_time_entries
                 WHERE company_id = :cid AND job_id = :job_id
                       AND technician_id = :tech AND clocked_out_at IS NULL
                 FOR UPDATE
                """
            ),
            {"cid": company_id, "job_id": job_id, "tech": technician_id},
        ).first()
        if open_entry is None:
            db.rollback()
            raise ValidationFailed(
                "technician is not clocked in on this job"
            )

        row = db.execute(
            text(
                """
                UPDATE job_time_entries
                   SET clocked_out_at = now(), updated_at = now(),
                       idempotency_key = COALESCE(idempotency_key, :key)
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"id": open_entry.id, "key": idempotency_key},
        ).first()
        db.commit()
    return row


def list_time_entries(db: Session, company_id: uuid.UUID, job_id: uuid.UUID) -> list[Row]:
    with tenant_context(db, company_id):
        _require_job(db, job_id)
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM job_time_entries
                     WHERE job_id = :job_id
                     ORDER BY clocked_in_at
                    """
                ),
                {"job_id": job_id},
            ).all()
        )
