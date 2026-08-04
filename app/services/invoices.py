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
            company_id, invoice_id, current.total, customer_email=customer_email
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
                "invoice has a payment recorded and cannot be voided; refunds are "
                "out of scope for this phase"
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
