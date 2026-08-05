"""Slips — tenant-scoped CRUD for wet slips, dry-stack spaces, and moorings
(Phase 15).

Deliberately thin, same posture as `app.services.vendors`: a slip is "a
rentable space with an identifier, a type, a status, and a rate", and the
interesting behavior (booking it, preventing double-booking, billing it)
lives in `app.services.slip_reservations`, not here.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, assignments, like_term

UPDATABLE_COLUMNS = frozenset(
    {
        "identifier",
        "slip_type",
        "status",
        "length_ft",
        "width_ft",
        "depth_ft",
        "rack_level",
        "rack_position",
        "latitude",
        "longitude",
        "monthly_rate",
        "daily_rate",
        "notes",
    }
)
_INSERT_COLUMNS = sorted(UPDATABLE_COLUMNS)


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "uq_slips_company_identifier" in detail:
        return Conflict("a slip with this identifier already exists")
    if "ck_slips_depth_only_wet_or_mooring" in detail:
        return Conflict("depth_ft may only be set on a wet_slip or mooring")
    if "ck_slips_rack_only_dry_stack" in detail:
        return Conflict("rack_level/rack_position may only be set on a dry_stack slip")
    if "ck_slips_latlng_pair" in detail:
        return Conflict("latitude and longitude must both be set or both be null")
    return Conflict("slip violates a database constraint")


_INSERT = text(
    f"""
    INSERT INTO slips (company_id, {", ".join(_INSERT_COLUMNS)})
    VALUES (:company_id, {", ".join(f":{c}" for c in _INSERT_COLUMNS)})
    RETURNING *
    """
)


def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    params = {"company_id": company_id} | {c: data.get(c) for c in _INSERT_COLUMNS}
    try:
        with tenant_context(db, company_id):
            row = db.execute(_INSERT, params).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def get(db: Session, company_id: uuid.UUID, slip_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(text("SELECT * FROM slips WHERE id = :id"), {"id": slip_id}).first()
    if row is None:
        raise NotFound(f"slip {slip_id} not found")
    return row


def list_slips(
    db: Session,
    company_id: uuid.UUID,
    *,
    slip_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id}
    if slip_type:
        clauses += " AND slip_type = CAST(:slip_type AS slip_type)"
        params["slip_type"] = slip_type
    if status:
        clauses += " AND status = CAST(:status AS slip_status)"
        params["status"] = status
    if search:
        clauses += " AND identifier ILIKE :term"
        params["term"] = like_term(search)

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM slips
                     WHERE company_id = :cid {clauses}
                     ORDER BY identifier
                    """
                ),
                params,
            ).all()
        )


def update(
    db: Session, company_id: uuid.UUID, slip_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, slip_id)

    statement = text(
        f"""
        UPDATE slips
           SET {assignments(changes, UPDATABLE_COLUMNS)}, updated_at = now()
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(statement, changes | {"id": slip_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    if row is None:
        raise NotFound(f"slip {slip_id} not found")
    return row


# ---------------------------------------------------------------------------
# availability — used by both the slip map and reservation creation
# ---------------------------------------------------------------------------
def is_available(
    db: Session,
    company_id: uuid.UUID,
    slip_id: uuid.UUID,
    start_date: Any,
    end_date: Any,
) -> bool:
    """True if no non-cancelled reservation on this slip overlaps the given
    (inclusive) date range.

    This is an advisory check only — a read, not a lock. The actual
    guarantee against double-booking is `ex_slip_reservations_no_overlap`
    (the `btree_gist` EXCLUDE constraint on `slip_reservations`); this
    function exists purely so the UI/API can tell a caller "this range looks
    free" without them having to attempt-and-catch an IntegrityError just to
    check availability.
    """
    with tenant_context(db, company_id):
        conflict = db.execute(
            text(
                """
                SELECT 1 FROM slip_reservations
                 WHERE slip_id = :slip_id
                   AND status <> 'cancelled'
                   AND stay_range && daterange(:start_date, :end_date, '[]')
                 LIMIT 1
                """
            ),
            {"slip_id": slip_id, "start_date": start_date, "end_date": end_date},
        ).first()
    return conflict is None
