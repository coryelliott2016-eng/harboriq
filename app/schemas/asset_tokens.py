"""Schemas for Phase 19's draft-only asset-token registration layer."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssetTokenType = Literal["vessel", "slip", "equipment", "receivable"]


class AssetTokenRegistrationCreate(BaseModel):
    """Register intent to tokenize an asset; no issuance or status is accepted."""

    asset_type: AssetTokenType
    vessel_id: uuid.UUID | None = None
    source_description: str = Field(min_length=1, max_length=5_000)
    estimated_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    notes: str | None = Field(default=None, max_length=5_000)


class AssetTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    asset_type: AssetTokenType
    vessel_id: uuid.UUID | None
    source_description: str
    estimated_value: Decimal | None
    notes: str | None
    status: Literal["draft"]
    created_by: uuid.UUID
    created_at: datetime


class TokenLedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_token_id: uuid.UUID
    company_id: uuid.UUID
    entry_type: Literal["registered"]
    recorded_at: datetime
    notes: str | None


class AssetTokenRegistrationResponse(BaseModel):
    asset_token: AssetTokenOut
    ledger_entry: TokenLedgerEntryOut
