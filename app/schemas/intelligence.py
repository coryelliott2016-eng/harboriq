"""Closed, public-data-only demo contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

Sector = Literal["service", "marina"]
Product = Literal["water_level", "currents"]
Station = Literal["8726520", "8518750", "9414290"]


class DemoSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted_safety_notice: Literal[True]

    @field_validator("accepted_safety_notice", mode="before")
    @classmethod
    def require_boolean_true(cls, value):
        if value is not True:
            raise ValueError("Explicit safety notice acceptance is required.")
        return value


class DemoSessionResponse(BaseModel):
    session_token: str
    expires_at: datetime
    requests_remaining: int


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector: Sector
    station: Station
    product: Product


class Measurement(BaseModel):
    time: str
    value: str
    unit: str


class AssistResponse(BaseModel):
    mode: Literal["live_public_data"] = "live_public_data"
    sector: Sector
    summary: str
    source_url: str
    source_name: str
    retrieved_at: datetime
    observed_at: datetime
    station: Station
    product: Product
    measurements: list[Measurement]
    warnings: list[str]
    requests_remaining: int
