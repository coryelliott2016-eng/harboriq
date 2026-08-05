"""Slip reservation request/response schemas (Phase 15)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptionalText


class SlipReservationCreate(BaseModel):
    slip_id: uuid.UUID
    customer_id: uuid.UUID
    vessel_id: uuid.UUID | None = None
    start_date: date
    end_date: date
    notes: OptionalText = None


class SlipReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    slip_id: uuid.UUID
    customer_id: uuid.UUID
    vessel_id: uuid.UUID | None
    status: str
    start_date: date
    end_date: date
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    cancelled_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SlipAvailabilityQuery(BaseModel):
    slip_id: uuid.UUID
    start_date: date
    end_date: date


class SlipAvailabilityOut(BaseModel):
    slip_id: uuid.UUID
    start_date: date
    end_date: date
    available: bool


class GenerateStorageChargeRequest(BaseModel):
    rate: Decimal | None = Field(default=None, ge=0)
    quantity: Decimal | None = Field(default=None, gt=0)
    description: OptionalText = None


class StorageChargeOut(BaseModel):
    """Echo of the `job_line_items` row a storage charge creates -- mirrors
    what a job-billed line item would look like, since storage lines live
    in the same table (see migration 0016's header comment). `job_id` is
    always null here; `slip_reservation_id` is always set.
    """

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID | None = None
    slip_reservation_id: uuid.UUID | None
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    taxable: bool
    invoice_id: uuid.UUID | None
    invoiced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GenerateInvoiceFromReservationRequest(BaseModel):
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
