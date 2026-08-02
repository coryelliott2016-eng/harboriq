"""Vessel request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptionalText

# Dimensions are NUMERIC(6,2) in the DB, so 9999.99 is the ceiling. Bounding
# them here turns an out-of-range hull length into a 422 instead of a 500 from
# a numeric overflow.
_MAX_DIMENSION_FT = Decimal("9999.99")


class VesselBase(BaseModel):
    name: OptionalText = Field(default=None, max_length=200)
    make: OptionalText = Field(default=None, max_length=100)
    model: OptionalText = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1850, le=2200)
    #: Hull Identification Number — unique per hull, so unique within a tenant.
    hull_id: OptionalText = Field(default=None, max_length=50)
    registration: OptionalText = Field(default=None, max_length=50)
    length_ft: Decimal | None = Field(default=None, gt=0, le=_MAX_DIMENSION_FT)
    beam_ft: Decimal | None = Field(default=None, gt=0, le=_MAX_DIMENSION_FT)
    draft_ft: Decimal | None = Field(default=None, gt=0, le=_MAX_DIMENSION_FT)
    engine_make: OptionalText = Field(default=None, max_length=100)
    engine_model: OptionalText = Field(default=None, max_length=100)
    engine_hours: int | None = Field(default=None, ge=0)
    engine_count: int | None = Field(default=None, ge=0, le=10)
    storage_location: OptionalText = Field(default=None, max_length=200)
    slip_number: OptionalText = Field(default=None, max_length=50)
    notes: OptionalText = None


class VesselCreate(VesselBase):
    #: A vessel always belongs to a customer in the same tenant.
    customer_id: uuid.UUID


class VesselUpdate(VesselBase):
    """Partial update. Only fields present in the body are written.

    `customer_id` is included so a boat can be reassigned when it changes hands.
    """

    customer_id: uuid.UUID | None = None


class VesselOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    name: str | None
    make: str | None
    model: str | None
    year: int | None
    hull_id: str | None
    registration: str | None
    length_ft: Decimal | None
    beam_ft: Decimal | None
    draft_ft: Decimal | None
    engine_make: str | None
    engine_model: str | None
    engine_hours: int | None
    engine_count: int
    storage_location: str | None
    slip_number: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
