"""Schemas for Phase 18's licensed-processor crypto payment rail."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CryptoPaymentIntentCreate(BaseModel):
    """Request a stablecoin checkout for part or all of a payable invoice."""

    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(default="usdc", min_length=1, max_length=16)


class CryptoPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    invoice_id: uuid.UUID
    provider: str
    provider_reference: str | None
    currency: str
    amount_requested: Decimal
    status: str
    created_at: datetime
    confirmed_at: datetime | None
    raw_metadata: dict[str, Any] | None


class CryptoPaymentIntentResponse(BaseModel):
    payment: CryptoPaymentOut
    checkout_url_or_address: str
