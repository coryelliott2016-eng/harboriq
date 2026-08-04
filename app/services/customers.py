"""Customers — tenant-scoped CRUD.

All statements run on the app role inside `tenant_context`, so RLS is the thing
that enforces isolation. `RETURNING *` lets the caller build a response without
a second round trip after the GUC has been reset by COMMIT.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services import geocoding
from app.services.crud import (
    Conflict,
    NotFound,
    ValidationFailed,
    assignments,
    like_term,
)

#: Columns a PATCH may write. Anything else is a programming error.
UPDATABLE_COLUMNS = frozenset(
    {
        "first_name", "last_name", "company_name", "email", "phone",
        "address_line1", "address_line2", "city", "state", "postal_code",
        "country", "notes",
    }
)

#: Address-bearing columns that, on any change, trigger re-geocoding into
#: `latitude`/`longitude` (see `_geocode_if_address_changed`). Not part of
#: `UPDATABLE_COLUMNS`'s write-through to `latitude`/`longitude` directly —
#: those two are always derived server-side, never accepted from the client.
_ADDRESS_COLUMNS = frozenset({"address_line1", "city", "state", "postal_code"})

_INSERT = text(
    """
    INSERT INTO customers
        (company_id, first_name, last_name, company_name, email, phone,
         address_line1, address_line2, city, state, postal_code, country, notes,
         latitude, longitude)
    VALUES
        (:company_id, :first_name, :last_name, :company_name, :email, :phone,
         :address_line1, :address_line2, :city, :state, :postal_code,
         :country, :notes, :latitude, :longitude)
    RETURNING *
    """
)


def _geocode_address(data: dict[str, Any]) -> tuple[Any, Any]:
    """Geocode a customer's address_line1/city/state/postal_code, if any is
    present. Graceful degradation: no address at all, or a geocoding
    failure (timeout, non-200, no match), both simply mean the customer is
    saved with null coordinates — never blocks the save. Consistent with how
    the dispatch engine already treats missing customer coordinates.
    """
    parts = [
        data.get("address_line1"),
        data.get("city"),
        data.get("state"),
        data.get("postal_code"),
    ]
    address = ", ".join(p for p in parts if p and str(p).strip())
    if not address:
        return None, None
    result = geocoding.geocode(address)
    return result if result is not None else (None, None)


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "ck_customers_has_a_name" in detail:
        return ValidationFailed(
            "a customer must keep at least one of first_name, last_name or company_name"
        )
    return Conflict("customer violates a uniqueness constraint")


def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    params = {"company_id": company_id} | {
        column: data.get(column) for column in sorted(UPDATABLE_COLUMNS)
    }
    params["latitude"], params["longitude"] = _geocode_address(params)
    try:
        with tenant_context(db, company_id):
            row = db.execute(_INSERT, params).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def get(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM customers WHERE id = :id"), {"id": customer_id}
        ).first()
    if row is None:
        raise NotFound(f"customer {customer_id} not found")
    return row


def list_customers(
    db: Session,
    company_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    """List customers, newest-relevant ordering by name.

    `search` matches any of the name fields, the email or the phone. See
    `like_term` for why the caller does not supply its own wildcards.
    """
    clause = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}
    if search:
        # One parenthesised group: without it the ORs would escape the
        # company_id conjunct and only RLS would be holding the line.
        clause = """
              AND (
                    (COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')
                     || ' ' || COALESCE(company_name, '')) ILIKE :term
                 OR email ILIKE :term
                 OR phone ILIKE :term
              )
        """
        params["term"] = like_term(search)

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM customers
                     WHERE company_id = :cid {clause}
                     ORDER BY last_name NULLS LAST, first_name NULLS LAST,
                              company_name NULLS LAST, created_at
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


def update(
    db: Session, company_id: uuid.UUID, customer_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, customer_id)

    write_columns = UPDATABLE_COLUMNS | {"latitude", "longitude"}
    if _ADDRESS_COLUMNS & set(changes):
        # Any address component changed -> re-geocode from the FULL address
        # (existing row values merged with the incoming changes), not just
        # the fields that happened to be in this PATCH, so e.g. changing
        # only `city` still geocodes the complete address rather than just
        # the new city name in isolation.
        current = get(db, company_id, customer_id)
        merged = {
            "address_line1": changes.get("address_line1", current.address_line1),
            "city": changes.get("city", current.city),
            "state": changes.get("state", current.state),
            "postal_code": changes.get("postal_code", current.postal_code),
        }
        changes = dict(changes)
        changes["latitude"], changes["longitude"] = _geocode_address(merged)

    statement = text(
        f"""
        UPDATE customers
           SET {assignments(changes, write_columns)}, updated_at = now()
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(statement, changes | {"id": customer_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    if row is None:
        raise NotFound(f"customer {customer_id} not found")
    return row


def delete(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> None:
    """Delete a customer.

    Vessels and jobs reference customers, so the database refuses to orphan
    service history. That is surfaced as a 409 rather than being forced through
    with a cascade — a shop that wants a customer gone must deal with the boats
    first, and losing a work order's owner silently would be worse.
    """
    with tenant_context(db, company_id):
        try:
            row = db.execute(
                text("DELETE FROM customers WHERE id = :id RETURNING id"),
                {"id": customer_id},
            ).first()
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise Conflict(
                "customer still has vessels or jobs; delete or reassign them first"
            ) from exc
    if row is None:
        raise NotFound(f"customer {customer_id} not found")
