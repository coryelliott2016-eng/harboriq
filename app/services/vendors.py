"""Vendors — tenant-scoped CRUD (Phase 13).

Deliberately thin: a vendor is just "who a purchase order is placed with",
following the same shape as `app.services.customers`/`app.services.vessels`
rather than inventing a new pattern.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, assignments, like_term

UPDATABLE_COLUMNS = frozenset({"name", "contact_email", "contact_phone", "notes"})
_INSERT_COLUMNS = sorted(UPDATABLE_COLUMNS)

_INSERT = text(
    f"""
    INSERT INTO vendors (company_id, {", ".join(_INSERT_COLUMNS)})
    VALUES (:company_id, {", ".join(f":{c}" for c in _INSERT_COLUMNS)})
    RETURNING *
    """
)


def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    params = {"company_id": company_id} | {c: data.get(c) for c in _INSERT_COLUMNS}
    with tenant_context(db, company_id):
        row = db.execute(_INSERT, params).first()
        db.commit()
    return row


def get(db: Session, company_id: uuid.UUID, vendor_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM vendors WHERE id = :id"), {"id": vendor_id}
        ).first()
    if row is None:
        raise NotFound(f"vendor {vendor_id} not found")
    return row


def list_vendors(
    db: Session, company_id: uuid.UUID, *, search: str | None = None
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id}
    if search:
        clauses = " AND name ILIKE :term"
        params["term"] = like_term(search)

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM vendors
                     WHERE company_id = :cid {clauses}
                     ORDER BY name
                    """
                ),
                params,
            ).all()
        )


def update(
    db: Session, company_id: uuid.UUID, vendor_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, vendor_id)

    statement = text(
        f"""
        UPDATE vendors
           SET {assignments(changes, UPDATABLE_COLUMNS)}, updated_at = now()
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(statement, changes | {"id": vendor_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("vendor update violates a database constraint") from exc
    if row is None:
        raise NotFound(f"vendor {vendor_id} not found")
    return row
