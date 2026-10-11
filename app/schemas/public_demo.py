"""Bounded, tenant-independent public demonstration contract."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.industry import Industry

MAX_PROMPT_CHARS = 2000
MAX_ANSWER_CHARS = 4000


class PublicDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industry: Industry
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)

    @field_validator("prompt")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value.strip()


class PublicDemoResponse(BaseModel):
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)
    industry: Industry
    disclaimer: str
