"""Inventory item request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptionalText, RequiredText


class UsePartRequest(BaseModel):
    item_id: str
    quantity: int = Field(gt=0)
    #: Bills the part to a work order in the same transaction as the deduction.
    #: Omit it for stock movements that are not against a job.
    job_id: uuid.UUID | None = None


class UsePartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_id: str
    remaining_on_hand: int


class InventoryItemBase(BaseModel):
    name: RequiredText = Field(max_length=200)
    sku: OptionalText = Field(default=None, max_length=100)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    retail_price: Decimal = Field(default=Decimal("0"), ge=0)
    #: Below this on-hand count, the item surfaces on
    #: `GET /inventory/reorder-suggestions`.
    reorder_point: int = Field(default=0, ge=0)
    default_vendor_id: uuid.UUID | None = None


class InventoryItemCreate(InventoryItemBase):
    """`quantity_on_hand` is intentionally not settable here — see
    `app.services.inventory.create`'s docstring: stock only ever arrives
    through a received purchase order.
    """


class InventoryItemUpdate(BaseModel):
    name: RequiredText | None = Field(default=None, max_length=200)
    sku: OptionalText = Field(default=None, max_length=100)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    retail_price: Decimal | None = Field(default=None, ge=0)
    reorder_point: int | None = Field(default=None, ge=0)
    default_vendor_id: uuid.UUID | None = None


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    sku: str | None
    unit_cost: Decimal
    retail_price: Decimal
    #: `inventory_items` (migration 0001) predates a currency column on most
    #: other money-bearing tables; always "USD" today (see `money_currency`
    #: DB enum) but exposed so a future multi-currency phase is additive.
    currency: str
    quantity_on_hand: int
    reorder_point: int
    low_stock_alerted: bool
    default_vendor_id: uuid.UUID | None
    #: `inventory_items` has no `updated_at` column (unlike most other
    #: tenant tables) -- only `created_at` -- a pre-existing schema shape
    #: from before this phase, not something Phase 13 changes.
    created_at: datetime


class ReorderSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    sku: str | None
    quantity_on_hand: int
    reorder_point: int
    default_vendor_id: uuid.UUID | None
    unit_cost: Decimal


class GeneratePORequest(BaseModel):
    vendor_id: uuid.UUID
    item_ids: list[uuid.UUID] = Field(min_length=1)
