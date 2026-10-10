"""Public demo contracts; no authentication or customer models."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings


class AIDemoStatus(BaseModel):
    available: bool
    message: str
    message_limit: int
    max_message_chars: int


class AIDemoSession(BaseModel):
    session_token: str
    expires_in: int


class AIDemoHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class AIDemoChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=10000)
    history: list[AIDemoHistoryMessage] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def bounded_content(self) -> "AIDemoChatRequest":
        if not self.message.strip() or len(self.message) > settings.ai_demo_max_message_chars:
            raise ValueError("Message is empty or exceeds the demo limit")
        if len(self.history) > settings.ai_demo_max_history_messages:
            raise ValueError("History exceeds the demo limit")
        if any(
            not item.content.strip() or len(item.content) > settings.ai_demo_max_message_chars
            for item in self.history
        ) or sum(len(item.content) for item in self.history) > settings.ai_demo_max_history_chars:
            raise ValueError("History content exceeds the demo limit")
        return self


class AIDemoChatResponse(BaseModel):
    """Reserved real-engine response contract; never fabricated."""

    answer: str
    remaining_messages: int
