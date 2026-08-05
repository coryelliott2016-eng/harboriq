"""Slip request/response schemas (Phase 15)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import OptionalText, RequiredText


class SlipCreate(BaseModel):
    identifier: RequiredText
    slip_type: str = "wet_slip"
    status: str = "available"
    length_ft: Decimal | None = Field(default=None, gt=0)
    width_ft: Decimal | None = Field(default=None, gt=0)
    depth_ft: Decimal | None = Field(default=None, gt=0)
    rack_level: int | None = Field(default=None, ge=0)
    rack_position: OptionalText = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    monthly_rate: Decimal = Field(default=Decimal("0"), ge=0)
    daily_rate: Decimal = Field(default=Decimal("0"), ge=0)
    notes: OptionalText = None

    @model_validator(mode="after")
    def _check_latlng_pair(self) -> "SlipCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be omitted")
        return self


class SlipUpdate(BaseModel):
    identifier: RequiredText | None = None
    slip_type: str | None = None
    status: str | None = None
    length_ft: Decimal | None = Field(default=None, gt=0)
    width_ft: Decimal | None = Field(default=None, gt=0)
    depth_ft: Decimal | None = Field(default=None, gt=0)
    rack_level: int | None = Field(default=None, ge=0)
    rack_position: OptionalText = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    monthly_rate: Decimal | None = Field(default=None, ge=0)
    daily_rate: Decimal | None = Field(default=None, ge=0)
    notes: OptionalText = None


class SlipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    identifier: str
    slip_type: str
    status: str
    length_ft: Decimal | None
    width_ft: Decimal | None
    depth_ft: Decimal | None
    rack_level: int | None
    rack_position: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    monthly_rate: Decimal
    daily_rate: Decimal
    notes: str | None
    created_at: datetime
    updated_at: datetime
