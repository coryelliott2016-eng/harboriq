"""Stripe Connect onboarding/status + dunning-sweep response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class ConnectOnboardingResponse(BaseModel):
    account_id: str
    onboarding_url: str


class ConnectStatusResponse(BaseModel):
    connected: bool
    account_id: str | None
    charges_enabled: bool
    details_submitted: bool


class DunningRunResponse(BaseModel):
    reminded_invoice_ids: list[str]
    count: int
