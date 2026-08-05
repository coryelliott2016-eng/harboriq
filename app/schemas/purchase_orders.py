"""Purchase order request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptionalText


class PurchaseOrderLineItemCreate(BaseModel):
    inventory_item_id: uuid.UUID
    quantity_ordered: int = Field(gt=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)


class PurchaseOrderCreate(BaseModel):
    vendor_id: uuid.UUID
    notes: OptionalText = None
    line_items: list[PurchaseOrderLineItemCreate] = Field(min_length=1)


class ReceiptLine(BaseModel):
    line_item_id: uuid.UUID
    quantity: int = Field(gt=0)


class ReceivePurchaseOrderRequest(BaseModel):
    receipts: list[ReceiptLine] = Field(min_length=1)


class PurchaseOrderLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    inventory_item_id: uuid.UUID
    quantity_ordered: int
    quantity_received: int
    unit_cost: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str
    created_by: uuid.UUID
    submitted_at: datetime | None
    received_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    line_items: list[PurchaseOrderLineItemOut] = Field(default_factory=list)
