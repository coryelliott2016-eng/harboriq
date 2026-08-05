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

            # Serialize concurrent bookings of the *same slip* with a
            # transaction-scoped advisory lock (auto-released on commit or
            # rollback below, same lifetime as everything else in this
            # transaction). Without this, N>=3 concurrent inserts racing
            # against `ex_slip_reservations_no_overlap` can deadlock --
            # Postgres has each waiting transaction take a ShareLock on the
            # others' not-yet-committed tuple to see whether it will commit,
            # and with three or more overlapping inserts that wait graph can
            # form a genuine cycle instead of resolving pairwise. Locking
            # per-slip means only one transaction is ever inserting/checking
            # for a given slip at a time, so the exclusion constraint never
            # has more than one concurrent writer left to referee -- it
            # remains the actual correctness guarantee (see module
            # docstring), this lock only removes the deadlock opportunity.
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"slip_reservation:{company_id}:{slip_id}"},
            )

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


# ---------------------------------------------------------------------------
# recurring monthly storage billing (Phase 17) — a scheduled counterpart to
# the staff-triggered `generate_storage_charge` above. `generate_storage_charge`
# refuses outright once ANY line item exists for a reservation, which is
# correct for a single stay but wrong for an ongoing monthly rental: a
# live-aboard/long-term slip tenant should be billed every period they
# remain checked in, not once ever. Rather than relaxing that guard (which
# would reopen the door to accidental double-billing of a short stay), this
# adds a period-scoped variant: one `storage`-kind line item per
# (reservation, calendar month) pair, found by checking whether a line
# already exists whose `created_at` falls in `[period_start, period_end)`.
# That makes a second call for the SAME month a no-op (idempotent, per the
# spec's explicit requirement) while a NEW month for the same still-active
# reservation is billed independently.
# ---------------------------------------------------------------------------
def _month_bounds(on: date) -> tuple[date, date]:
    """Return `[first_of_month, first_of_next_month)` containing `on`."""
    period_start = on.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    return period_start, period_end


#: Reservation statuses billed by the recurring monthly sweep. `checked_in`
#: is the obvious case (a boat currently occupying the slip); `confirmed` is
#: included too so a reservation that spans a monthly rollover but hasn't
#: had its check-in recorded yet (e.g. staff forgot to click "check in" on
#: day one) still gets billed for the period rather than silently skipped —
#: `pending`/`checked_out`/`cancelled` are excluded (never occupied, or no
#: longer occupying, the slip).
RECURRING_BILLABLE_STATUSES = ("confirmed", "checked_in")


def generate_recurring_monthly_charge(
    db: Session,
    company_id: uuid.UUID,
    reservation_id: uuid.UUID,
    *,
    as_of: date,
) -> Row | None:
    """Idempotently bill one reservation for the calendar month containing `as_of`.

    Returns the new `job_line_items` row, or `None` if a charge for this
    reservation + month already exists (already billed — not an error, a
    scheduled sweep calling this twice for the same period is the expected
    "idempotent" case) or the reservation is not currently in a billable
    status / does not span this month at all.

    Rate: the slip's `monthly_rate` (this is the recurring-rent variant of
    storage billing, as opposed to `generate_storage_charge`'s nightly
    `daily_rate` default for a short stay) with `quantity=1` (one month's
    rent), so overriding just the unit price later — e.g. a prorated partial
    month — stays possible without changing the shape of the line item.
    """
    period_start, period_end = _month_bounds(as_of)

    with tenant_context(db, company_id):
        reservation = db.execute(
            text("SELECT * FROM slip_reservations WHERE id = :id"), {"id": reservation_id}
        ).first()
        if reservation is None:
            raise NotFound(f"slip reservation {reservation_id} not found")

        if reservation.status not in RECURRING_BILLABLE_STATUSES:
            return None

        # The reservation must actually span at least one day of this month
        # -- a reservation that ended last month or starts next month is not
        # billable for THIS period even if it is nominally "confirmed".
        if reservation.end_date < period_start or reservation.start_date >= period_end:
            return None

        # Idempotency key: the exact "<period_start> to <period_end>" marker
        # embedded in the description below. `created_at` (real insert
        # wall-clock time) is NOT a safe idempotency signal here -- `as_of`
        # is caller-supplied and can simulate any calendar month (tests,
        # backfills, a sweep that runs late), so a charge for "June" could
        # easily be inserted in real-world August. Matching on the period
        # marker itself is exact and immune to when the row happened to be
        # written.
        period_marker = f"{period_start.isoformat()} to {period_end.isoformat()}"
        already_billed_this_period = db.execute(
            text(
                """
                SELECT 1 FROM job_line_items
                 WHERE slip_reservation_id = :id
                   AND kind = 'storage'
                   AND description LIKE '%' || :period_marker
                 LIMIT 1
                """
            ),
            {"id": reservation_id, "period_marker": period_marker},
        ).first()
        if already_billed_this_period is not None:
            return None

        slip_row = db.execute(
            text("SELECT monthly_rate, identifier FROM slips WHERE id = :id"),
            {"id": reservation.slip_id},
        ).first()
        if slip_row is None:
            raise NotFound(f"slip {reservation.slip_id} not found")

        description = f"Slip {slip_row.identifier} monthly storage: {period_marker}"

        line = db.execute(
            text(
                """
                INSERT INTO job_line_items
                    (company_id, slip_reservation_id, kind, description, quantity, unit_price)
                VALUES
                    (:company_id, :reservation_id, 'storage', :description, 1, :unit_price)
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "reservation_id": reservation_id,
                "description": description,
                "unit_price": slip_row.monthly_rate,
            },
        ).first()
        db.commit()
    return line


def generate_recurring_monthly_charges_for_company(
    db: Session, company_id: uuid.UUID, *, as_of: date
) -> dict[str, int]:
    """Enumerate every `confirmed`/`checked_in` reservation for one company
    that overlaps the calendar month containing `as_of` and bill each one
    (idempotently — see `generate_recurring_monthly_charge`).

    Returns `{"reservations_considered": N, "charges_created": M}` so the
    Celery task and its tests can assert on both "did we look at the right
    rows" and "did we actually (not) double-charge."
    """
    period_start, period_end = _month_bounds(as_of)
    with tenant_context(db, company_id):
        reservation_ids = [
            row.id
            for row in db.execute(
                text(
                    """
                    SELECT id FROM slip_reservations
                     WHERE company_id = :cid
                       AND status = ANY(:statuses)
                       AND start_date < :period_end
                       AND end_date >= :period_start
                    """
                ),
                {
                    "cid": company_id,
                    "statuses": list(RECURRING_BILLABLE_STATUSES),
                    "period_start": period_start,
                    "period_end": period_end,
                },
            ).all()
        ]

    created = 0
    for reservation_id in reservation_ids:
        line = generate_recurring_monthly_charge(
            db, company_id, reservation_id, as_of=as_of
        )
        if line is not None:
            created += 1

    return {"reservations_considered": len(reservation_ids), "charges_created": created}


__all__ = [
    "cancel",
    "check_in",
    "check_out",
    "confirm",
    "create",
    "generate_recurring_monthly_charge",
    "generate_recurring_monthly_charges_for_company",
    "generate_storage_charge",
    "get",
    "list_reservations",
]
