"""Invoice request/response schemas.

There is no separate "invoice line item create" schema: invoices are built
FROM a job's existing, already-validated `job_line_items` (see
`app/schemas/jobs.py::JobLineItemCreate` for how those are entered) — this
phase only adds the schemas for turning a job's uninvoiced lines into a bill
and moving it through its lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import JobLineItemKind


class InvoiceCreate(BaseModel):
    job_id: uuid.UUID
    #: 0..1, e.g. 0.07 for 7%. Applied to the taxable subtotal only.
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, decimal_places=4)


class InvoiceLineItemOut(BaseModel):
    """A `job_line_items` row as it appears frozen onto an invoice."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    kind: JobLineItemKind
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    taxable: bool
    invoiced_at: datetime | None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    estimate_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    status: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    tax_rate: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    due_date: datetime | None
    sent_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    stripe_payment_intent_id: str | None
    stripe_checkout_session_id: str | None
    created_at: datetime
    updated_at: datetime


class InvoiceDetail(InvoiceOut):
    """A single invoice with the lines it froze."""

    line_items: list[InvoiceLineItemOut] = []


class InvoiceListItem(InvoiceOut):
    """Same shape as `InvoiceOut` today; kept distinct so the list endpoint
    can grow summary-only fields later without changing the detail shape."""


class InvoiceSendResponse(BaseModel):
    invoice: InvoiceOut
    #: One-time value — the raw token is never retrievable again after this
    #: response, matching `public_tokens.issue_public_token`'s contract.
    pay_token: str
    pay_url: str


class VoidInvoiceResponse(BaseModel):
    invoice: InvoiceOut
