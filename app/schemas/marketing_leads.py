"""Schemas for public marketing / trial signup leads."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TeamSize = Literal["solo", "team", "business", "enterprise"]
Industry = Literal[
    "marina_or_boatyard",
    "marine_towing_or_assistance",
    "commercial_fishing",
    "recreational_fishing",
    "marine_repair",
    "yacht_or_charter_operations",
    "boat_owner",
    "dealer_or_broker",
    "supplier_or_manufacturer",
    "surveyor_or_insurance",
    "commercial_fleet",
    "other_marine_business",
]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MarketingLeadCreate(BaseModel):
    """Body for POST /api/v1/public/leads.

    `website` is a honeypot — real browsers leave it blank; bots that fill
    every field are accepted with a fake success so they do not learn the
    trap. Never stored.
    """

    full_name: str = Field(min_length=1, max_length=120)
    business_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    team_size: TeamSize = "solo"
    industry: Industry | None = None
    source: str = Field(default="marketing-signup", max_length=64)
    website: str = Field(default="", max_length=200)

    @field_validator("full_name", "business_name", "email", "source", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v.lower()


class MarketingLeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    business_name: str
    email: str
    team_size: str
    industry: str | None = None
    source: str
    notified_at: datetime | None = None
    created_at: datetime


class MarketingLeadCreateResponse(BaseModel):
    ok: bool = True
    id: uuid.UUID
    duplicate: bool = False
    message: str


class MarketingLeadListResponse(BaseModel):
    count: int
    leads: list[MarketingLeadOut]
