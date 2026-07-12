"""Webhook request body is the raw Stripe event JSON."""
from pydantic import BaseModel


class StripeObject(BaseModel):
    id: str | None = None
    object: str | None = None
    metadata: dict | None = None
    # per-event fields are accessed loosely in the handler
    model_config = {"extra": "allow"}


class StripeEventData(BaseModel):
    object: dict
    model_config = {"extra": "allow"}


class StripeEvent(BaseModel):
    id: str
    type: str
    data: StripeEventData
    model_config = {"extra": "allow"}
