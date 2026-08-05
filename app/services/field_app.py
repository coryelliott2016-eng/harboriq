"""Field-app service layer (Phase 12): job attachments and time-clock entries.

Both mutation paths are designed to be safely replayable by the frontend's
offline-sync queue: a caller-supplied `idempotency_key` is stored on the row,
and a repeat call with the same key returns the original row instead of
inserting/transitioning a second time (see README, "Offline queue
idempotency"). Everything else follows the same tenant-scoped,
`tenant_context`-armed, raw-SQL discipline as `app.services.jobs`.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, ValidationFailed


def _require_job(db: Session, job_id: uuid.UUID) -> None:
    found = db.execute(text("SELECT 1 FROM jobs WHERE id = :id"), {"id": job_id}).first()
    if found is None:
        raise NotFound(f"job {job_id} not found")


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
) -> Row:
    """Open a time entry for `technician_id` on `job_id`.

    Refuses a second concurrent clock-in for the same (job, technician) pair
    (`uq_job_time_entries_one_open_per_tech_job`) — the technician must clock
    out first. An idempotent replay of the SAME clock-in (matching key)
    returns the entry it already created instead of a 409.
    """
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
) -> Row:
    """Close the technician's open time entry on this job.

    `ValidationFailed` if there is no open entry to close. An idempotent
    replay (matching key, entry already closed) returns the closed row
    rather than erroring — closing an already-closed entry a second time via
    the offline queue must be a no-op, not a failure.
    """
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
