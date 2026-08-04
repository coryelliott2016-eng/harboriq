"""Bridges the DB (invoice + line items + customer + vessel + company) to
`app.services.invoice_pdf`'s DB-agnostic renderer.

Kept separate from `invoice_pdf.py` on purpose: `invoice_pdf` has zero DB
imports and is trivially unit-testable with hand-built dataclasses; this
module is the (thin, easy to mock) glue that the outbox consumer and any
future "download PDF" endpoint both call.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.invoice_pdf import InvoicePdfData, InvoicePdfLineItem, render_invoice_pdf


def build_invoice_pdf_bytes(db: Session, invoice_id: uuid.UUID) -> bytes | None:
    """Render one invoice to PDF bytes, resolving its tenant first.

    Returns `None` if the invoice cannot be found under any tenant (e.g. it
    was somehow deleted between being queued and dispatch) rather than
    raising — callers (the outbox consumer) treat a `None` as "skip the
    attachment, still send the email".

    Uses the SERVICE session (BYPASSRLS) to resolve `company_id` from the
    invoice id first, then re-scopes to that tenant's `tenant_context` for
    everything else, matching the pattern `stripe_webhooks.py` uses for
    webhook-driven, not-yet-tenant-scoped lookups.
    """
    company_row = db.execute(
        text("SELECT company_id FROM invoices WHERE id = :id"), {"id": invoice_id}
    ).first()
    if company_row is None:
        return None
    company_id = company_row.company_id

    with tenant_context(db, company_id):
        invoice = db.execute(
            text(
                """
                SELECT id, status, currency, subtotal, tax_total, total,
                       amount_paid, balance_due, customer_id
                  FROM invoices WHERE id = :id
                """
            ),
            {"id": invoice_id},
        ).first()
        if invoice is None:
            return None

        company = db.execute(
            text("SELECT name FROM companies WHERE id = :id"), {"id": company_id}
        ).first()

        customer = None
        if invoice.customer_id is not None:
            customer = db.execute(
                text(
                    """
                    SELECT first_name, last_name, company_name, email
                      FROM customers WHERE id = :id
                    """
                ),
                {"id": invoice.customer_id},
            ).first()

        vessel = db.execute(
            text(
                """
                SELECT v.name AS vessel_name
                  FROM job_line_items jli
                  JOIN jobs j ON j.id = jli.job_id
                  LEFT JOIN vessels v ON v.id = j.vessel_id
                 WHERE jli.invoice_id = :invoice_id AND v.name IS NOT NULL
                 LIMIT 1
                """
            ),
            {"invoice_id": invoice_id},
        ).first()

        line_items = db.execute(
            text(
                """
                SELECT description, quantity, unit_price, line_total
                  FROM job_line_items
                 WHERE invoice_id = :invoice_id
                 ORDER BY created_at, id
                """
            ),
            {"invoice_id": invoice_id},
        ).all()

    customer_name = None
    if customer is not None:
        customer_name = customer.company_name or " ".join(
            part for part in (customer.first_name, customer.last_name) if part
        ) or None

    data = InvoicePdfData(
        invoice_id=invoice.id,
        company_name=(company.name if company else "HarborIQ"),
        status=invoice.status,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        balance_due=invoice.balance_due,
        currency=invoice.currency,
        customer_name=customer_name,
        customer_email=(customer.email if customer else None),
        vessel_name=(vessel.vessel_name if vessel else None),
        # Best-effort: only the checkout session id (not a durable pay URL)
        # is stored on the row; the outbox payload's `pay_url` is the
        # authoritative link and already appears in the email body, so the
        # PDF omits a pay link entirely rather than fabricate one here. A
        # future phase could pass the actual pay_url through explicitly.
        pay_url=None,
        line_items=[
            InvoicePdfLineItem(
                description=row.description,
                quantity=row.quantity,
                unit_price=row.unit_price,
                line_total=row.line_total,
            )
            for row in line_items
        ],
    )
    return render_invoice_pdf(data)
