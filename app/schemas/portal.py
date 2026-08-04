"""Portal (customer-facing, token-gated) response schemas.

Deliberately narrower than the internal `*Out` schemas — no internal notes,
no cost/margin detail, nothing about other customers. See
`app.services.portal` for the read-side isolation guarantees these wrap.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PortalVesselOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str | None
    make: str | None
    model: str | None
    year: int | None
    hull_id: str | None
    registration: str | None


class PortalMeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    company_name: str | None
    email: str | None
    phone: str | None
    vessels: list[PortalVesselOut] = []


class PortalJobOut(BaseModel):
    """Status/schedule/technician only — no internal notes or pricing."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str | None
    status: str
    scheduled_at: datetime | None
    scheduled_end_at: datetime | None
    completed_at: datetime | None
    vessel_id: uuid.UUID | None
    technician_name: str | None


class PortalInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    due_date: datetime | None
    paid_at: datetime | None
    created_at: datetime
    #: `GET /portal/invoices/{id}/pay-url` hands back a fresh checkout link
    #: on demand (reusing `get_or_create_checkout_url`) rather than this list
    #: eagerly creating a Stripe session per invoice per page load.


class PortalEstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    approved_at: datetime | None
    created_at: datetime


class PortalApproveTokenOut(BaseModel):
    """A fresh, single-purpose `estimate_approve` token handed to the portal
    so its "Approve" button can call the SAME existing public approval
    endpoint — `POST /public/estimate/{token}/approve` — rather than the
    portal duplicating approval logic."""

    approve_path: str


class PortalInviteOut(BaseModel):
    """Returned to staff after issuing/renewing a customer's portal link.

    The raw token itself is never returned here — same discipline as every
    other `issue_public_token` caller: the link goes out over the outbox
    email, and this response only confirms it was queued.
    """

    customer_id: uuid.UUID
    outbox_event_id: int
