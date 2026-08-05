"""Slip reservations — pending/confirmed/checked_in/checked_out lifecycle
against a slip, plus storage-billing generation onto `job_line_items`
(Phase 15).

Status is never written directly: every lifecycle function reloads the row
`FOR UPDATE`, hands the current and target values to
`app.services.state_machines.SlipReservationSM`, and only then writes — the
same discipline `app.services.jobs.set_status`/`app.services.purchase_orders`
already use.

Double-booking is NOT prevented here. `create` does an advisory
`slips.is_available` check first (so a normal, non-racing caller gets a
clean 409 instead of a raw IntegrityError), but the real guarantee is
`ex_slip_reservations_no_overlap`, the `btree_gist` EXCLUDE constraint on
`slip_reservations(slip_id, stay_range)` added by migration 0016 — two
concurrent inserts that both pass the advisory check because neither has
committed yet will still have exactly one of them rejected by Postgres at
COMMIT/INSERT time. See `tests/test_slip_reservation_overlap.py` for the
concurrency test proving this.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services import slips
from app.services.crud import Conflict, NotFound, ValidationFailed
from app.services.state_machines import IllegalTransition, SlipReservationSM


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "ex_slip_reservations_no_overlap" in detail:
        return Conflict("this slip is already booked for an overlapping date range")
    if "fk_slip_reservations_slip" in detail:
        return NotFound("slip not found")
    if "fk_slip_reservations_customer" in detail:
        return NotFound("customer not found")
    if "fk_slip_reservations_vessel" in detail:
        return NotFound("vessel not found")
    if "ck_slip_reservations_dates" in detail:
        return ValidationFailed("end_date must be on or after start_date")
    return Conflict("slip reservation violates a database constraint")


def _require_row(db: Session, table: str, row_id: uuid.UUID, label: str) -> None:
    found = db.execute(
        text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}  # noqa: S608
    ).first()
    if found is None:
        raise NotFound(f"{label} {row_id} not found")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def create(
    db: Session,
    company_id: uuid.UUID,
    slip_id: uuid.UUID,
    customer_id: uuid.UUID,
    start_date: date,
    end_date: date,
    *,
    vessel_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> Row:
    """Create a `pending` reservation for `slip_id` covering [start_date, end_date].

    Refuses up front (an advisory, non-locking check) if the slip is already
    booked for an overlapping range on a non-cancelled reservation; the
    database's EXCLUDE constraint is the actual enforcement (see module
    docstring) and still applies even if this check races and misses.
    """
    if end_date < start_date:
        raise ValidationFailed("end_date must be on or after start_date")

    try:
        with tenant_context(db, company_id):
            _require_row(db, "slips", slip_id, "slip")
            _require_row(db, "customers", customer_id, "customer")
            if vessel_id is not None:
                _require_row(db, "vessels", vessel_id, "vessel")

            if not slips.is_available(db, company_id, slip_id, start_date, end_date):
                db.rollback()
                raise Conflict(
                    "this slip is already booked for an overlapping date range"
                )

            row = db.execute(
                text(
                    """
                    INSERT INTO slip_reservations
                        (company_id, slip_id, customer_id, vessel_id, start_date, end_date, notes)
                    VALUES
                        (:company_id, :slip_id, :customer_id, :vessel_id, :start_date, :end_date, :notes)
                    RETURNING *
                    """
                ),
                {
                    "company_id": company_id,
                    "slip_id": slip_id,
                    "customer_id": customer_id,
                    "vessel_id": vessel_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "notes": notes,
                },
            ).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
def get(db: Session, company_id: uuid.UUID, reservation_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM slip_reservations WHERE id = :id"), {"id": reservation_id}
        ).first()
    if row is None:
        raise NotFound(f"slip reservation {reservation_id} not found")
    return row


def list_reservations(
    db: Session,
    company_id: uuid.UUID,
    *,
    slip_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id}
    if slip_id is not None:
        clauses += " AND slip_id = :slip_id"
        params["slip_id"] = slip_id
    if customer_id is not None:
        clauses += " AND customer_id = :customer_id"
        params["customer_id"] = customer_id
    if status:
        clauses += " AND status = CAST(:status AS slip_reservation_status)"
        params["status"] = status

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM slip_reservations
                     WHERE company_id = :cid {clauses}
                     ORDER BY start_date DESC, created_at DESC
                    """
                ),
                params,
            ).all()
        )


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def _transition(
    db: Session,
    company_id: uuid.UUID,
    reservation_id: uuid.UUID,
    target: str,
    extra_set_sql: str = "",
) -> Row:
    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status FROM slip_reservations WHERE id = :id FOR UPDATE"),
            {"id": reservation_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"slip reservation {reservation_id} not found")
        try:
            SlipReservationSM.assert_transition(current.status, target)
        except IllegalTransition:
            db.rollback()
            raise

        row = db.execute(
            text(
                f"""
                UPDATE slip_reservations
                   SET status = CAST(:status AS slip_reservation_status),
                       updated_at = now() {extra_set_sql}
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"status": target, "id": reservation_id},
        ).first()

        # Occupying a slip is a real fact about the physical world, so
        # check-in/check-out also flip the slip's own `status` — same
        # "the record reflects reality, not just paperwork" posture as
        # purchase-order receipt incrementing quantity_on_hand.
        if target == "checked_in":
            db.execute(
                text("UPDATE slips SET status = 'occupied', updated_at = now() WHERE id = :id"),
                {"id": row.slip_id},
            )
        elif target in ("checked_out", "cancelled"):
            db.execute(
                text(
                    "UPDATE slips SET status = 'available', updated_at = now() "
                    "WHERE id = :id AND status = 'occupied'"
                ),
                {"id": row.slip_id},
            )
        db.commit()
    return row


def confirm(db: Session, company_id: uuid.UUID, reservation_id: uuid.UUID) -> Row:
    """Move `pending -> confirmed` — the marina has accepted the booking."""
    return _transition(db, company_id, reservation_id, "confirmed")


def check_in(db: Session, company_id: uuid.UUID, reservation_id: uuid.UUID) -> Row:
    """Move `confirmed -> checked_in` and mark the slip `occupied`."""
    return _transition(
        db, company_id, reservation_id, "checked_in", ", checked_in_at = now()"
    )


def check_out(db: Session, company_id: uuid.UUID, reservation_id: uuid.UUID) -> Row:
    """Move `checked_in -> checked_out` and free the slip back to `available`."""
    return _transition(
        db, company_id, reservation_id, "checked_out", ", checked_out_at = now()"
    )


def cancel(db: Session, company_id: uuid.UUID, reservation_id: uuid.UUID) -> Row:
    """Cancel a `pending` or `confirmed` reservation.

    Cancelling also removes the reservation from
    `ex_slip_reservations_no_overlap`'s comparison set (the constraint's
    `WHERE (status <> 'cancelled')` clause) — the slip's dates free up for a
    new booking immediately, not just visually.
    """
    return _transition(
        db, company_id, reservation_id, "cancelled", ", cancelled_at = now()"
    )


# ---------------------------------------------------------------------------
# storage billing — generates a job_line_items row, same shape as a job's
# labor/part/fee lines, then hands off to app.services.invoices to freeze it
# onto an actual invoice (Phase 15 reuses Phase 3's invoicing machinery
# rather than inventing a parallel one; see migration 0016's header comment
# and app.services.invoices.create_invoice_from_reservation).
# ---------------------------------------------------------------------------
def generate_storage_charge(
    db: Session,
    company_id: uuid.UUID,
    reservation_id: uuid.UUID,
    *,
    rate: Decimal | None = None,
    quantity: Decimal | None = None,
    description: str | None = None,
) -> Row:
    """Create one `storage`-kind `job_line_items` row billing this reservation.

    Defaults: `quantity` is the number of nights actually stayed
    (`end_date - start_date`, at least 1 -- a same-day reservation still
    occupied the slip for a night), `rate` is the slip's `daily_rate`. Both
    can be overridden (e.g. to bill the slip's `monthly_rate` instead, or a
    negotiated rate) by the caller. Refused if this reservation has already
    been billed once (uninvoiced OR invoiced lines both count — a second
    call is very likely a duplicate-billing mistake, not an intentional
    second charge; a genuinely separate charge, e.g. a second month's rent,
    should be modeled as a second reservation).
    """
    with tenant_context(db, company_id):
        reservation = db.execute(
            text("SELECT * FROM slip_reservations WHERE id = :id"), {"id": reservation_id}
        ).first()
        if reservation is None:
            raise NotFound(f"slip reservation {reservation_id} not found")

        already_billed = db.execute(
            text("SELECT 1 FROM job_line_items WHERE slip_reservation_id = :id LIMIT 1"),
            {"id": reservation_id},
        ).first()
        if already_billed is not None:
            raise Conflict("this reservation already has a storage charge generated")

        slip_row = db.execute(
            text("SELECT daily_rate, identifier FROM slips WHERE id = :id"),
            {"id": reservation.slip_id},
        ).first()
        if slip_row is None:
            raise NotFound(f"slip {reservation.slip_id} not found")

        nights = (reservation.end_date - reservation.start_date).days
        resolved_quantity = quantity if quantity is not None else Decimal(max(nights, 1))
        resolved_rate = rate if rate is not None else slip_row.daily_rate
        resolved_description = (
            description
            or f"Slip {slip_row.identifier} storage: "
            f"{reservation.start_date.isoformat()} to {reservation.end_date.isoformat()}"
        )

        line = db.execute(
            text(
                """
                INSERT INTO job_line_items
                    (company_id, slip_reservation_id, kind, description, quantity, unit_price)
                VALUES
                    (:company_id, :reservation_id, 'storage', :description, :quantity, :unit_price)
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "reservation_id": reservation_id,
                "description": resolved_description,
                "quantity": resolved_quantity,
                "unit_price": resolved_rate,
            },
        ).first()
        db.commit()
    return line


__all__ = [
    "cancel",
    "check_in",
    "check_out",
    "confirm",
    "create",
    "generate_storage_charge",
    "get",
    "list_reservations",
]
