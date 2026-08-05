"""Invoices — built from a job's uninvoiced `job_line_items`, mirroring the
row-locking / state-machine discipline of `app.services.jobs`.

There is deliberately no separate invoice-line-items table: `job_line_items`
was designed in migration 0003 to carry `invoice_id`/`invoiced_at` for exactly
this purpose. Creating an invoice freezes a job's uninvoiced lines by pointing
them at the new invoice row; voiding un-freezes them. `line_total` is a
DB-generated column, so the invoice's subtotal is always computed FROM the
frozen rows rather than re-derived and risking drift.

Every write here runs inside `tenant_context` on the app role, exactly like
`jobs.py` — RLS, not a remembered WHERE clause, is what keeps tenants apart.
Every status transition loads the row `FOR UPDATE` before calling
`InvoiceSM.assert_transition`, so two concurrent requests serialise instead of
double-applying (see `jobs.py::set_status`'s docstring for why that ordering
matters).
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services import outbox, public_tokens, stripe_billing
from app.services.crud import Conflict, NotFound
from app.services.state_machines import InvoiceSM

#: Generous — a customer may need to reload the pay page many times across
#: weeks before completing checkout; the token is a read-only lookup key, not
#: a one-shot action (see `public_tokens.py` and the "do not burn on read"
#: contract for `invoice_pay` tokens documented in the spec/README).
INVOICE_PAY_TOKEN_MAX_USES = 50
INVOICE_PAY_TOKEN_TTL_HOURS = 24 * 30  # ~30 days


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def create_invoice(
    db: Session,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    tax_rate: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Invoice every currently-uninvoiced line on `job_id`.

    Locks the candidate lines with `FOR UPDATE` before computing totals, so a
    concurrent second `create_invoice` call for the same job cannot also grab
    them — the loser sees zero uninvoiced rows and gets the "nothing to
    invoice" 409 rather than splitting the same line across two invoices.
    """
    with tenant_context(db, company_id):
        job = db.execute(
            text("SELECT id, customer_id FROM jobs WHERE id = :id"), {"id": job_id}
        ).first()
        if job is None:
            db.rollback()
            raise NotFound(f"job {job_id} not found")

        lines = db.execute(
            text(
                """
                SELECT id, line_total, taxable
                  FROM job_line_items
                 WHERE job_id = :job_id AND invoice_id IS NULL
                 FOR UPDATE
                """
            ),
            {"job_id": job_id},
        ).all()
        if not lines:
            db.rollback()
            raise Conflict(f"job {job_id} has no uninvoiced line items")

        subtotal = sum((row.line_total for row in lines), Decimal("0"))
        taxable_subtotal = sum(
            (row.line_total for row in lines if row.taxable), Decimal("0")
        )
        tax_total = _quantize(taxable_subtotal * tax_rate)
        total = subtotal + tax_total

        invoice = db.execute(
            text(
                """
                INSERT INTO invoices
                    (company_id, estimate_id, customer_id, status, subtotal,
                     tax_total, total, amount_paid, balance_due, tax_rate)
                VALUES
                    (:company_id, NULL, :customer_id, 'draft', :subtotal,
                     :tax_total, :total, 0, :total, :tax_rate)
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "customer_id": job.customer_id,
                "subtotal": subtotal,
                "tax_total": tax_total,
                "total": total,
                "tax_rate": tax_rate,
            },
        ).first()

        line_ids = [row.id for row in lines]
        db.execute(
            text(
                """
                UPDATE job_line_items
                   SET invoice_id = :invoice_id, invoiced_at = now()
                 WHERE id = ANY(:ids)
                """
            ),
            {"invoice_id": invoice.id, "ids": line_ids},
        )
        db.commit()

    return {
        "invoice": invoice,
        "line_items": list_invoice_line_items(db, company_id, invoice.id),
    }


# ---------------------------------------------------------------------------
# create (from a slip reservation) — Phase 15's storage billing, reusing
# this exact same freeze-the-line-items machinery instead of a parallel one
# ---------------------------------------------------------------------------
def create_invoice_from_reservation(
    db: Session,
    company_id: uuid.UUID,
    reservation_id: uuid.UUID,
    tax_rate: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Invoice every currently-uninvoiced `storage`-kind line on `reservation_id`.

    Identical shape to `create_invoice`, just keyed off
    `slip_reservation_id` instead of `job_id` -- see migration 0016's header
    comment and `app.services.slip_reservations.generate_storage_charge` for
    why a slip reservation's rental charge is a `job_line_items` row (despite
    the table's name) rather than a separate invoice-line-item table.
    """
    with tenant_context(db, company_id):
        reservation = db.execute(
            text("SELECT id, customer_id FROM slip_reservations WHERE id = :id"),
            {"id": reservation_id},
        ).first()
        if reservation is None:
            db.rollback()
            raise NotFound(f"slip reservation {reservation_id} not found")

        lines = db.execute(
            text(
                """
                SELECT id, line_total, taxable
                  FROM job_line_items
                 WHERE slip_reservation_id = :reservation_id AND invoice_id IS NULL
                 FOR UPDATE
                """
            ),
            {"reservation_id": reservation_id},
        ).all()
        if not lines:
            db.rollback()
            raise Conflict(f"slip reservation {reservation_id} has no uninvoiced line items")

        subtotal = sum((row.line_total for row in lines), Decimal("0"))
        taxable_subtotal = sum(
            (row.line_total for row in lines if row.taxable), Decimal("0")
        )
        tax_total = _quantize(taxable_subtotal * tax_rate)
        total = subtotal + tax_total

        invoice = db.execute(
            text(
                """
                INSERT INTO invoices
                    (company_id, estimate_id, customer_id, status, subtotal,
                     tax_total, total, amount_paid, balance_due, tax_rate)
                VALUES
                    (:company_id, NULL, :customer_id, 'draft', :subtotal,
                     :tax_total, :total, 0, :total, :tax_rate)
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "customer_id": reservation.customer_id,
                "subtotal": subtotal,
                "tax_total": tax_total,
                "total": total,
                "tax_rate": tax_rate,
            },
        ).first()

        line_ids = [row.id for row in lines]
        db.execute(
            text(
                """
                UPDATE job_line_items
                   SET invoice_id = :invoice_id, invoiced_at = now()
                 WHERE id = ANY(:ids)
                """
            ),
            {"invoice_id": invoice.id, "ids": line_ids},
        )
        db.commit()

    return {
        "invoice": invoice,
        "line_items": list_invoice_line_items(db, company_id, invoice.id),
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
def get(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM invoices WHERE id = :id"), {"id": invoice_id}
        ).first()
    if row is None:
        raise NotFound(f"invoice {invoice_id} not found")
    return row


def _connect_account_id(db: Session, company_id: uuid.UUID) -> str | None:
    """The tenant's Stripe Connect Standard account id, if onboarded.

    `None` (the common case for most tenants today) means "not connected
    yet" -- every checkout-session call site treats that as "fall back to
    HarborIQ's own platform account", exactly like the pre-Connect behavior.
    """
    row = db.execute(
        text("SELECT stripe_connect_account_id FROM companies WHERE id = :id"),
        {"id": company_id},
    ).first()
    return row.stripe_connect_account_id if row else None


def get_or_create_checkout_url(
    db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID
) -> str | None:
    """For the public pay page: reuse a stored Stripe Checkout URL, or create
    one lazily if none exists yet (e.g. the invoice was sent before Stripe was
    configured). Returns None if the invoice is already paid/void/etc, or if
    Stripe is unavailable — never raises for a missing Stripe key.

    This does not change invoice status or touch a public token's use count;
    it is safe to call on every page load.
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                SELECT id, status, total, currency, customer_id,
                       stripe_checkout_session_id
                  FROM invoices WHERE id = :id
                """
            ),
            {"id": invoice_id},
        ).first()
        if row is None:
            raise NotFound(f"invoice {invoice_id} not found")

        if row.status in {"paid", "void", "uncollectible", "refunded"}:
            return None

        # We only ever persisted the session ID, not its URL (Stripe session
        # URLs are not meant to be stored/reused indefinitely, and a stale one
        # 404s from Stripe's side) -- always mint a fresh session for the pay
        # page rather than try to reconstruct or cache a URL.
        customer_email = None
        if row.customer_id is not None:
            cust = db.execute(
                text("SELECT email FROM customers WHERE id = :id"),
                {"id": row.customer_id},
            ).first()
            customer_email = cust.email if cust else None

        session = stripe_billing.create_checkout_session(
            company_id, invoice_id, row.total, currency=row.currency,
            customer_email=customer_email,
            stripe_account=_connect_account_id(db, company_id),
        )
        if session is None:
            return None

        db.execute(
            text(
                "UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"
            ),
            {"sid": session["id"], "id": invoice_id},
        )
        db.commit()
        return session["url"]


def list_invoice_line_items(
    db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID
) -> list[Row]:
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM job_line_items
                     WHERE invoice_id = :invoice_id
                     ORDER BY created_at, id
                    """
                ),
                {"invoice_id": invoice_id},
            ).all()
        )


def list_invoices(
    db: Session,
    company_id: uuid.UUID,
    *,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}

    if status is not None:
        clauses += " AND status = :status"
        params["status"] = status
    if customer_id is not None:
        clauses += " AND customer_id = :customer_id"
        params["customer_id"] = customer_id
    if job_id is not None:
        # Invoices have no direct job_id column (they bill from a job's
        # lines, potentially several jobs' worth in a future phase); filter
        # through the line items they froze.
        clauses += """ AND id IN (
            SELECT DISTINCT invoice_id FROM job_line_items
             WHERE job_id = :job_id AND invoice_id IS NOT NULL
        )"""
        params["job_id"] = job_id

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM invoices
                     WHERE company_id = :cid {clauses}
                     ORDER BY created_at DESC
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def send_invoice(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> dict[str, Any]:
    """Move `draft -> sent`, issue a public pay link, best-effort Stripe.

    A Stripe outage or unset API key must not block sending the invoice — the
    shop can still hand the customer a pay link and collect payment another
    way, and the checkout session can be created lazily later (see
    `GET /public/invoice/{token}`). Nothing about the invoice's own state
    depends on Stripe succeeding.
    """
    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status, total, customer_id FROM invoices WHERE id = :id FOR UPDATE"),
            {"id": invoice_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"invoice {invoice_id} not found")

        try:
            InvoiceSM.assert_transition(current.status, "sent")
        except Exception:
            db.rollback()
            raise

        customer_email = None
        if current.customer_id is not None:
            row = db.execute(
                text("SELECT email FROM customers WHERE id = :id"),
                {"id": current.customer_id},
            ).first()
            customer_email = row.email if row else None

        session = stripe_billing.create_checkout_session(
            company_id, invoice_id, current.total, customer_email=customer_email,
            stripe_account=_connect_account_id(db, company_id),
        )
        checkout_session_id = session["id"] if session else None

        invoice = db.execute(
            text(
                """
                UPDATE invoices
                   SET status = 'sent',
                       sent_at = now(),
                       stripe_checkout_session_id =
                           COALESCE(:session_id, stripe_checkout_session_id)
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"id": invoice_id, "session_id": checkout_session_id},
        ).first()

        raw_token = public_tokens.issue_public_token(
            db,
            company_id,
            "invoice",
            invoice_id,
            "invoice_pay",
            ttl_hours=INVOICE_PAY_TOKEN_TTL_HOURS,
            max_uses=INVOICE_PAY_TOKEN_MAX_USES,
        )
        pay_url = f"/api/v1/public/invoice/{raw_token}"

        outbox.enqueue(
            db,
            company_id,
            "invoice.send",
            {
                "invoice_id": str(invoice_id),
                "company_id": str(company_id),
                "pay_url": pay_url,
                "customer_email": customer_email,
            },
        )
        db.commit()

    return {"invoice": invoice, "pay_token": raw_token, "pay_url": pay_url}


def void_invoice(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> Row:
    """Move to `void`, refusing if anything has ever been collected.

    On success the invoice's line items are freed back to uninvoiced
    (`invoice_id`/`invoiced_at` cleared) — a voided invoice was never actually
    charged, so its lines are not billing history, they are just billable
    work again and can be picked up by the next `create_invoice` call.
    """
    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status, amount_paid FROM invoices WHERE id = :id FOR UPDATE"),
            {"id": invoice_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"invoice {invoice_id} not found")

        if current.amount_paid and current.amount_paid > 0:
            db.rollback()
            raise Conflict(
                "invoice has a payment recorded and cannot be voided; use "
                "POST /invoices/{id}/refund to return money on a paid/partially "
                "paid invoice instead"
            )

        try:
            InvoiceSM.assert_transition(current.status, "void")
        except Exception:
            db.rollback()
            raise

        invoice = db.execute(
            text(
                """
                UPDATE invoices
                   SET status = 'void', voided_at = now()
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"id": invoice_id},
        ).first()

        db.execute(
            text(
                """
                UPDATE job_line_items
                   SET invoice_id = NULL, invoiced_at = NULL
                 WHERE invoice_id = :id
                """
            ),
            {"id": invoice_id},
        )
        db.commit()

    return invoice


# ---------------------------------------------------------------------------
# webhook-driven payment
# ---------------------------------------------------------------------------
def mark_paid_from_webhook(
    db: Session,
    company_id: uuid.UUID,
    *,
    stripe_checkout_session_id: str | None = None,
    stripe_payment_intent_id: str | None = None,
    amount_paid_cents: int,
) -> dict[str, Any]:
    """Apply a Stripe payment to the invoice it belongs to.

    Called from inside the webhook handler's existing `tenant_context` (the
    caller has already resolved and armed `company_id` and de-duplicated the
    Stripe event id in the same transaction). Resolves the invoice by
    whichever Stripe id is present, row-locks it, and transitions it to
    `paid` (fully covered) or `partial` (a lesser amount) via `InvoiceSM` —
    never by direct assignment.
    """
    if stripe_checkout_session_id is not None:
        where = "stripe_checkout_session_id = :session_id"
        params: dict[str, Any] = {"session_id": stripe_checkout_session_id}
    elif stripe_payment_intent_id is not None:
        where = "stripe_payment_intent_id = :pi"
        params = {"pi": stripe_payment_intent_id}
    else:
        raise NotFound("no Stripe identifier provided to resolve an invoice")

    current = db.execute(
        text(f"SELECT * FROM invoices WHERE {where} FOR UPDATE"), params
    ).first()
    if current is None:
        raise NotFound("invoice not found for the given Stripe identifier")

    amount_paid = _quantize(Decimal(amount_paid_cents) / Decimal(100))
    new_amount_paid = current.amount_paid + amount_paid
    # Clamp: a webhook cannot be allowed to push amount_paid past total —
    # ck_invoices_amount_paid_lte_total would reject it as a 500 otherwise,
    # and an over-payment is a Stripe/ops anomaly to investigate, not silently
    # swallow.
    new_amount_paid = min(new_amount_paid, current.total)
    target_status = "paid" if new_amount_paid >= current.total else "partial"

    InvoiceSM.assert_transition(current.status, target_status)

    paid_at_clause = ", paid_at = now()" if target_status == "paid" else ""
    invoice = db.execute(
        text(
            f"""
            UPDATE invoices
               SET status = CAST(:status AS invoice_status),
                   amount_paid = :amount_paid,
                   balance_due = total - :amount_paid,
                   stripe_payment_intent_id =
                       COALESCE(:pi, stripe_payment_intent_id){paid_at_clause}
             WHERE id = :id
            RETURNING *
            """
        ),
        {
            "status": target_status,
            "amount_paid": new_amount_paid,
            "pi": stripe_payment_intent_id,
            "id": current.id,
        },
    ).first()

    payment = db.execute(
        text(
            """
            INSERT INTO payments
                (company_id, invoice_id, status, amount, stripe_charge_id)
            VALUES (:cid, :invoice_id, 'succeeded', :amount, :charge_id)
            RETURNING *
            """
        ),
        {
            "cid": company_id,
            "invoice_id": current.id,
            "amount": amount_paid,
            "charge_id": stripe_payment_intent_id,
        },
    ).first()

    return {"invoice": invoice, "payment": payment}


# ---------------------------------------------------------------------------
# refunds
# ---------------------------------------------------------------------------
class RefundFailed(Exception):
    """Raised when Stripe rejects/cannot process a refund request."""


def refund_invoice(
    db: Session,
    company_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    amount: Decimal | None = None,
    reason: str | None = None,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Refund all or part of a paid/partially-paid invoice via Stripe.

    Only legal from `paid` or `partial` (see `InvoiceSM`); `amount=None`
    means "refund the full amount_paid". A partial amount transitions the
    invoice to `partially_refunded`; refunding the full amount_paid
    transitions it to `refunded`. Both are terminal in `InvoiceSM`, matching
    the state machine that has allowed these transitions since Phase 3 (see
    `InvoiceSM.transitions["paid"]`).

    Row-locks the invoice before validating and calling Stripe, exactly like
    every other lifecycle transition in this module, so two concurrent
    refund requests against the same invoice serialize rather than race.
    """
    with tenant_context(db, company_id):
        current = db.execute(
            text(
                """
                SELECT status, amount_paid, total, stripe_payment_intent_id
                  FROM invoices WHERE id = :id FOR UPDATE
                """
            ),
            {"id": invoice_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"invoice {invoice_id} not found")

        if current.amount_paid is None or current.amount_paid <= 0:
            db.rollback()
            raise Conflict("invoice has no payment recorded to refund")

        already_refunded = db.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE invoice_id = :id"
            ),
            {"id": invoice_id},
        ).first().total
        remaining_refundable = current.amount_paid - already_refunded

        refund_amount = _quantize(amount) if amount is not None else remaining_refundable
        if refund_amount <= 0 or refund_amount > remaining_refundable:
            db.rollback()
            raise Conflict(
                f"refund amount must be between 0.01 and the remaining refundable "
                f"amount ({remaining_refundable})"
            )

        # "refunded" means "the invoice was paid in full, and that full
        # amount has now been returned" -- which requires BOTH that the
        # invoice's `total` was fully collected (amount_paid == total; a
        # "partial"/deposit invoice never satisfies this) AND that this
        # refund exhausts everything collected so far (refund_amount ==
        # remaining_refundable). Checking amount_paid vs. total, rather
        # than the current status string, is what lets this stay correct
        # across repeated partial refunds (status is already
        # "partially_refunded" by the second call, but the invoice may
        # still have been paid in full originally).
        was_paid_in_full = current.amount_paid == current.total
        target_status = (
            "refunded"
            if was_paid_in_full and refund_amount == remaining_refundable
            else "partially_refunded"
        )
        try:
            InvoiceSM.assert_transition(current.status, target_status)
        except Exception:
            db.rollback()
            raise

        result = stripe_billing.create_refund(
            payment_intent_id=current.stripe_payment_intent_id,
            charge_id=None,
            amount=refund_amount,
            reason=reason,
            stripe_account=_connect_account_id(db, company_id),
        )
        if result is None:
            db.rollback()
            raise RefundFailed(
                "Stripe refund could not be created (not configured, or the API call failed)"
            )

        invoice = db.execute(
            text(
                """
                UPDATE invoices
                   SET status = CAST(:status AS invoice_status)
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"status": target_status, "id": invoice_id},
        ).first()

        refund = db.execute(
            text(
                """
                INSERT INTO refunds
                    (company_id, invoice_id, amount, reason, stripe_refund_id, created_by)
                VALUES
                    (:cid, :invoice_id, :amount, :reason, :stripe_refund_id, :created_by)
                RETURNING *
                """
            ),
            {
                "cid": company_id,
                "invoice_id": invoice_id,
                "amount": refund_amount,
                "reason": reason,
                "stripe_refund_id": result["id"],
                "created_by": created_by,
            },
        ).first()

        db.commit()

    return {"invoice": invoice, "refund": refund}


# ---------------------------------------------------------------------------
# refund webhook reconciliation (Phase 17, Area E)
# ---------------------------------------------------------------------------
def reconcile_refund_from_webhook(
    db: Session,
    company_id: uuid.UUID,
    *,
    stripe_refund_id: str,
    stripe_payment_intent_id: str | None,
    stripe_charge_id: str | None,
    amount_refunded_cents: int,
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Reconcile a refund issued OUTSIDE HarborIQ (directly in the Stripe
    Dashboard, or via Stripe's API by someone bypassing `POST
    /invoices/{id}/refund`) against the local `invoices`/`refunds` tables.

    Triggered by the `charge.refunded` webhook event. Distinct from
    `refund_invoice` above: that function is the OUTBOUND path (HarborIQ
    calls Stripe to create the refund); this is the INBOUND reconciliation
    path (Stripe already performed the refund -- possibly with zero
    involvement from HarborIQ -- and this just needs to catch the local
    books up). It never calls `stripe_billing.create_refund` and never hits
    the Stripe API at all.

    Resolves the invoice by `stripe_payment_intent_id` first (the strong,
    already-indexed identifier `mark_paid_from_webhook` also keys off of),
    falling back to `stripe_charge_id` if present, matching how Stripe's
    `charge.refunded` payload carries both `payment_intent` and the charge
    id. Returns None (a no-op, logged by the caller) if no invoice can be
    resolved -- e.g. a charge that has nothing to do with a HarborIQ
    invoice, such as the platform's own Stripe Billing subscription charge.

    Idempotent on `stripe_refund_id`: `charge.refunded` fires once per
    refund object, but Stripe may still redeliver the same event, and a
    charge can have MULTIPLE `refunds.data[]` entries (successive partial
    refunds against one charge all raise the same event type again with a
    growing `refunds.data` array) -- so this is called once per refund id
    the caller has not seen before, not once per event.
    """
    with tenant_context(db, company_id):
        where_clauses = []
        params: dict[str, Any] = {}
        if stripe_payment_intent_id:
            where_clauses.append("stripe_payment_intent_id = :pi")
            params["pi"] = stripe_payment_intent_id
        if stripe_charge_id:
            where_clauses.append("stripe_payment_intent_id = :charge_as_pi")
            params["charge_as_pi"] = stripe_charge_id
        if not where_clauses:
            return None

        current = db.execute(
            text(
                f"""
                SELECT id, status, amount_paid, total
                  FROM invoices
                 WHERE {" OR ".join(where_clauses)}
                 FOR UPDATE
                """
            ),
            params,
        ).first()
        if current is None:
            # Not a HarborIQ invoice charge (e.g. the platform's own Stripe
            # Billing subscription) -- nothing to reconcile.
            return None

        # Idempotency: a refund id we've already recorded (either from our
        # own `refund_invoice` outbound call, or a prior delivery of this
        # same webhook) is a no-op, not a duplicate refund row.
        existing = db.execute(
            text("SELECT id FROM refunds WHERE stripe_refund_id = :rid"),
            {"rid": stripe_refund_id},
        ).first()
        if existing is not None:
            return None

        already_refunded = db.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE invoice_id = :id"
            ),
            {"id": current.id},
        ).first().total

        refund_amount = _quantize(Decimal(amount_refunded_cents) / Decimal(100))
        remaining_refundable = current.amount_paid - already_refunded
        # Unlike `refund_invoice`, this reconciles a refund that ALREADY
        # happened in Stripe -- clamp rather than reject, since the money
        # has already moved regardless of what our local ledger expected.
        was_paid_in_full = current.amount_paid == current.total
        target_status = (
            "refunded"
            if was_paid_in_full and refund_amount >= remaining_refundable
            else "partially_refunded"
        )

        try:
            InvoiceSM.assert_transition(current.status, target_status)
        except Exception:
            db.rollback()
            raise

        invoice = db.execute(
            text(
                """
                UPDATE invoices
                   SET status = CAST(:status AS invoice_status)
                 WHERE id = :id
                RETURNING *
                """
            ),
            {"status": target_status, "id": current.id},
        ).first()

        refund = db.execute(
            text(
                """
                INSERT INTO refunds
                    (company_id, invoice_id, amount, reason, stripe_refund_id)
                VALUES
                    (:cid, :invoice_id, :amount, :reason, :stripe_refund_id)
                ON CONFLICT (stripe_refund_id) WHERE stripe_refund_id IS NOT NULL
                DO NOTHING
                RETURNING *
                """
            ),
            {
                "cid": company_id,
                "invoice_id": current.id,
                "amount": refund_amount,
                "reason": reason or "Refunded via Stripe Dashboard",
                "stripe_refund_id": stripe_refund_id,
            },
        ).first()

        db.commit()

    return {"invoice": invoice, "refund": refund}
