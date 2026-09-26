"""Estimate request/response schemas (staff side).

An estimate is a priced proposal for work on a job. Line items reuse the
same vocabulary and bounds as `job_line_items` (see `app/schemas/jobs.py`) so
an approved estimate converts into an invoice without re-mapping:

* `labor` — fractional hours allowed (e.g. 1.50 h at the shop's hourly rate),
* `part`  — optionally linked to an inventory item,
* `fee`   — flat charges such as a diagnostic fee, haul-out or travel fee.

Customer-side viewing and approval already exist (portal + public token);
these schemas only cover the staff workflow.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptionalText, RequiredText

_MAX_QUANTITY = Decimal("10000")
_MAX_UNIT_PRICE = Decimal("100000")
_MAX_LINES = 100

EstimateLineKind = Literal["labor", "part", "fee"]


class EstimateLineItemCreate(BaseModel):
    kind: EstimateLineKind
    description: RequiredText = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, le=_MAX_QUANTITY, decimal_places=2)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, le=_MAX_UNIT_PRICE,
                                decimal_places=2)
    taxable: bool = True
    #: Only valid for `part` lines.
    inventory_item_id: uuid.UUID | None = None


class EstimateCreate(BaseModel):
    job_id: uuid.UUID
    #: 0..1, e.g. 0.07 for 7%. Applied to the taxable subtotal only.
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, decimal_places=4)
    notes: OptionalText = Field(default=None, max_length=2000)
    line_items: list[EstimateLineItemCreate] = Field(min_length=1, max_length=_MAX_LINES)


class EstimateLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    estimate_id: uuid.UUID
    kind: str
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    taxable: bool
    inventory_item_id: uuid.UUID | None
    position: int


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    job_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    status: str
    currency: str
    subtotal: Decimal
    tax_rate: Decimal
    tax_total: Decimal
    total: Decimal
    notes: str | None
    sent_at: datetime | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EstimateDetail(EstimateOut):
    line_items: list[EstimateLineItemOut] = []
    #: Set once the estimate has been converted; `None` otherwise.
    invoice_id: uuid.UUID | None = None


class EstimateSendResponse(BaseModel):
    estimate: EstimateOut
    #: True when a customer email was queued; False when the customer has no
    #: email on file (staff must share the portal link another way).
    email_queued: bool


class EstimateConvertResponse(BaseModel):
    estimate: EstimateOut
    invoice_id: uuid.UUID
