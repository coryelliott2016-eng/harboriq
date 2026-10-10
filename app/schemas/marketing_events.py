"""Only consented, allowlisted event names can enter aggregate analytics."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

MarketingEvent = Literal[
    "homepage_view",
    "demo_launch",
    "category_select",
    "first_question",
    "ai_response",
    "demo_error",
    "early_access_click",
    "lead_submitted",
]


class MarketingEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: MarketingEvent
    consent: Literal[True]

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit analytics consent is required")
        return value
