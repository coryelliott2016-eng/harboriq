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
    db: Session,
    company_id: uuid.UUID,
    *,
    search: str | None = None,
    include_inactive: bool = False,
) -> list[Row]:
    """Default view is active vendors only -- an archived vendor should not
    show up for "who do I order parts from" workflows. `include_inactive`
    is for the rare screen that needs to show/manage archived vendors
    (e.g. an admin "show archived" toggle); it does NOT affect
    `get()`, which always resolves a vendor by id regardless of
    `is_active` so historical purchase orders keep rendering correctly.
    """
    clauses = "" if include_inactive else " AND is_active = true"
    params: dict[str, Any] = {"cid": company_id}
    if search:
        clauses += " AND name ILIKE :term"
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


def set_active(
    db: Session, company_id: uuid.UUID, vendor_id: uuid.UUID, is_active: bool
) -> Row:
    """Deactivate ("archive") or reactivate a vendor.

    Deliberately a dedicated action rather than folded into the generic
    `update()`/`VendorUpdate` PATCH -- same reasoning as
    `app.services.jobs.set_status`: a status/lifecycle change is a distinct
    operation from an ordinary field edit, and keeping it separate makes it
    easy to add e.g. an audit-log entry or "can't reactivate if X" rule
    later without touching the free-text-field update path.
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                UPDATE vendors
                   SET is_active = :is_active, updated_at = now()
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"id": vendor_id, "is_active": is_active},
        ).first()
        db.commit()
    if row is None:
        raise NotFound(f"vendor {vendor_id} not found")
    return row
