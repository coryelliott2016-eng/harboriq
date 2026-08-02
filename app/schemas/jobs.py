"""Job (work order) request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import JobLineItemKind, JobPriority, JobStatus
from app.schemas.common import OptionalText, RequiredText

# `job_line_items.line_total` is a NUMERIC(12,2) generated column, so the
# PRODUCT of quantity and unit_price must fit in 10 integral digits. These
# bounds keep any accepted pair well inside that, turning what would otherwise
# be a numeric-overflow 500 into a 422.
_MAX_QUANTITY = Decimal("10000")
_MAX_UNIT_PRICE = Decimal("100000")


class JobBase(BaseModel):
    title: OptionalText = Field(default=None, max_length=200)
    description: OptionalText = None
    priority: JobPriority | None = None
    scheduled_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    vessel_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    notes: OptionalText = None


class JobCreate(JobBase):
    customer_id: uuid.UUID
    title: RequiredText = Field(min_length=1, max_length=200)
    priority: JobPriority = JobPriority.NORMAL


class JobUpdate(JobBase):
    """Partial update of the job's descriptive and scheduling fields.

    `status` is deliberately absent: it moves only through
    `POST /jobs/{id}/status`, which validates the transition against `JobSM`.
    """

    customer_id: uuid.UUID | None = None


class JobStatusUpdate(BaseModel):
    status: JobStatus
    #: Recorded when moving to `on_hold` so the board can show why.
    hold_reason: OptionalText = Field(default=None, max_length=500)


class JobAssign(BaseModel):
    #: Null unassigns the job.
    technician_id: uuid.UUID | None = None


class JobLineItemCreate(BaseModel):
    kind: JobLineItemKind
    description: RequiredText = Field(min_length=1, max_length=500)
    #: Fractional for labor hours (1.50), whole numbers for a parts count.
    quantity: Decimal = Field(gt=0, le=_MAX_QUANTITY, decimal_places=2)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, le=_MAX_UNIT_PRICE,
                                decimal_places=2)
    taxable: bool = True
    #: Only valid for `part` lines. Recording it here does NOT deduct stock —
    #: POST /api/v1/inventory/use is what moves inventory.
    inventory_item_id: uuid.UUID | None = None


class JobLineItemUpdate(BaseModel):
    description: OptionalText = Field(default=None, min_length=1, max_length=500)
    quantity: Decimal | None = Field(default=None, gt=0, le=_MAX_QUANTITY,
                                     decimal_places=2)
    unit_price: Decimal | None = Field(default=None, ge=0, le=_MAX_UNIT_PRICE,
                                       decimal_places=2)
    taxable: bool | None = None


class JobLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    kind: JobLineItemKind
    description: str
    inventory_item_id: uuid.UUID | None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    taxable: bool
    inventory_committed: bool
    invoice_id: uuid.UUID | None
    invoiced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    vessel_id: uuid.UUID | None
    title: str
    description: str | None
    status: JobStatus
    priority: JobPriority
    scheduled_at: datetime | None
    scheduled_end_at: datetime | None
    technician_id: uuid.UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    canceled_at: datetime | None
    hold_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class JobDetail(JobOut):
    """A single job with its billable lines."""

    line_items: list[JobLineItemOut] = []
