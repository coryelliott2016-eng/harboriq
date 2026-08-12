"""Live dispatch board schemas (Phase 11): location ping + on-my-way SMS."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LocationPing(BaseModel):
    """`POST /users/me/location-ping` body — one Geolocation API reading.

    Bounds match real-world latitude/longitude ranges, not this platform's
    marine-service-area assumption — the same generosity `Customer.latitude`/
    `longitude` already allow (see `app/schemas/customers.py`), so a
    technician traveling anywhere on Earth cannot be rejected by an
    artificially narrow bound.
    """

    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class LocationPingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    current_latitude: Decimal
    current_longitude: Decimal
    location_updated_at: datetime
    # Marine threat model Scenario 2 (2026-08-11): true when implied ground
    # speed from the prior ping exceeds the configured plausibility ceiling.
    # Informational only — the coordinates were still accepted.
    anomaly_suspected: bool = False
    implied_speed_kmh: float | None = None


class TechnicianLocationOut(BaseModel):
    """One row of the dispatch board map's technician layer.

    `is_live` is true only when the coordinates came from an actual
    location-ping (`location_updated_at` is set); false means the map is
    falling back to the technician's static home base because no ping has
    ever been received — the map/legend uses this to be honest about which
    pins are "live-ish" versus "best guess".
    """

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    is_live: bool
    location_updated_at: datetime | None


class OnMyWayResponse(BaseModel):
    outbox_event_id: int | None
