"""Vessels — tenant-scoped CRUD, always owned by a customer.

The owning customer is checked under RLS before the insert so an unknown or
another tenant's id produces a clean 404. The composite FK
`(company_id, customer_id) -> customers(company_id, id)` from migration 0003 is
the actual guarantee; this lookup only turns it into a good error message.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import (
    Conflict,
    NotFound,
    ValidationFailed,
    assignments,
    like_term,
)

UPDATABLE_COLUMNS = frozenset(
    {
        "customer_id", "name", "make", "model", "year", "hull_id", "registration",
        "length_ft", "beam_ft", "draft_ft", "engine_make", "engine_model",
        "engine_hours", "engine_count", "storage_location", "slip_number", "notes",
    }
)

#: Columns settable at creation time; `engine_count` has a DB default of 1.
_INSERT_COLUMNS = sorted(UPDATABLE_COLUMNS)

_INSERT = text(
    f"""
    INSERT INTO vessels (company_id, {", ".join(_INSERT_COLUMNS)})
    VALUES (:company_id, {", ".join(f":{c}" for c in _INSERT_COLUMNS)})
    RETURNING *
    """
)


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "uq_vessels_company_hull_id" in detail:
        return Conflict("a vessel with this hull id already exists")
    if "fk_vessels_customer" in detail:
        return NotFound("customer not found")
    return Conflict("vessel violates a database constraint")


def _require_customer(db: Session, customer_id: uuid.UUID) -> None:
    """Assert the customer is visible in the caller's tenant. Assumes RLS is armed."""
    exists = db.execute(
        text("SELECT 1 FROM customers WHERE id = :id"), {"id": customer_id}
    ).first()
    if exists is None:
        raise NotFound(f"customer {customer_id} not found")


def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    params = {"company_id": company_id} | {
        column: data.get(column) for column in _INSERT_COLUMNS
    }
    # engine_count is NOT NULL with a default; an omitted value must not
    # become an explicit NULL.
    if params.get("engine_count") is None:
        params["engine_count"] = 1

    try:
        with tenant_context(db, company_id):
            _require_customer(db, data["customer_id"])
            row = db.execute(_INSERT, params).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def get(db: Session, company_id: uuid.UUID, vessel_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM vessels WHERE id = :id"), {"id": vessel_id}
        ).first()
    if row is None:
        raise NotFound(f"vessel {vessel_id} not found")
    return row


def list_vessels(
    db: Session,
    company_id: uuid.UUID,
    *,
    customer_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}
    if customer_id is not None:
        clauses += " AND customer_id = :customer_id"
        params["customer_id"] = customer_id
    if search:
        clauses += """
              AND (name ILIKE :term OR make ILIKE :term OR model ILIKE :term
                   OR hull_id ILIKE :term OR slip_number ILIKE :term)
        """
        params["term"] = like_term(search)

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM vessels
                     WHERE company_id = :cid {clauses}
                     ORDER BY name NULLS LAST, created_at
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


def update(
    db: Session, company_id: uuid.UUID, vessel_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, vessel_id)
    if "customer_id" in changes and changes["customer_id"] is None:
        raise ValidationFailed("a vessel must belong to a customer")

    statement = text(
        f"""
        UPDATE vessels
           SET {assignments(changes, UPDATABLE_COLUMNS)}, updated_at = now()
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            if "customer_id" in changes:
                _require_customer(db, changes["customer_id"])
            row = db.execute(statement, changes | {"id": vessel_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    if row is None:
        raise NotFound(f"vessel {vessel_id} not found")
    return row


def delete(db: Session, company_id: uuid.UUID, vessel_id: uuid.UUID) -> None:
    """Delete a vessel. Refused while work orders still reference it."""
    with tenant_context(db, company_id):
        try:
            row = db.execute(
                text("DELETE FROM vessels WHERE id = :id RETURNING id"),
                {"id": vessel_id},
            ).first()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise Conflict(
                "vessel is referenced by existing jobs; delete or reassign them first"
            ) from exc
    if row is None:
        raise NotFound(f"vessel {vessel_id} not found")
