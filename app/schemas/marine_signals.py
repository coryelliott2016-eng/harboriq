"""Schemas for tenant-scoped Marine Signals."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

SignalCategory = Literal[
    "weather", "environment", "safety_recall", "regulation",
    "season", "training", "fuel", "market",
]
SignalPriority = Literal["normal", "urgent"]
SignalFeedbackKind = Literal["saved", "dismissed", "flagged", "useful", "acted"]

# The first pilot only polls feeds hosted by these known primary/official domains.
CURATED_SOURCE_HOSTS = frozenset(
    {
        "noaa.gov", "weather.gov", "fwc.gov", "uscg.mil",
        "abycinc.org", "aaa.com", "conference-board.org", "yanmar.com",
    }
)


def _validated_https_url(value: str | HttpUrl) -> str:
    url = str(value)
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or not any(host == domain or host.endswith(f".{domain}") for domain in CURATED_SOURCE_HOSTS)
    ):
        raise ValueError("URL must use HTTPS and belong to an approved pilot source domain")
    return url


class MarineSignalSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: SignalCategory
    source_url: HttpUrl
    feed_url: HttpUrl
    terms_url: HttpUrl
    terms_confirmed: Literal[True]

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_url", "feed_url", "terms_url")
    @classmethod
    def approved_urls(cls, value: HttpUrl) -> str:
        return _validated_https_url(value)

    @model_validator(mode="after")
    def feed_must_match_source_host(self) -> "MarineSignalSourceCreate":
        if urlsplit(str(self.source_url)).hostname != urlsplit(str(self.feed_url)).hostname:
            raise ValueError("feed URL must use the same host as the source URL")
        return self


class MarineSignalSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: SignalCategory
    source_url: str
    feed_url: str
    terms_url: str
    terms_reviewed_at: datetime
    enabled: bool
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime


class MarineSignalCreate(BaseModel):
    source_id: uuid.UUID
    category: SignalCategory
    title: str = Field(min_length=3, max_length=250)
    source_content: str = Field(default="", max_length=10000)
    summary: str = Field(default="", max_length=2000)
    why_it_matters: str = Field(default="", max_length=1500)
    suggested_action: str = Field(default="", max_length=1500)
    citation_url: HttpUrl
    published_at: datetime | None = None
    effective_until: datetime | None = None
    geography: str = Field(default="", max_length=200)
    uncertainty: str = Field(default="", max_length=1000)
    priority: SignalPriority = "normal"

    @field_validator("citation_url")
    @classmethod
    def citation_must_be_https(cls, value: HttpUrl) -> str:
        if value.scheme != "https":
            raise ValueError("citation URL must use HTTPS")
        return str(value)

    @model_validator(mode="after")
    def expiration_after_publication(self) -> "MarineSignalCreate":
        if (
            self.published_at is not None
            and self.effective_until is not None
            and self.effective_until <= self.published_at
        ):
            raise ValueError("effective_until must be after published_at")
        return self


class MarineSignalReview(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    why_it_matters: str = Field(min_length=1, max_length=1500)
    suggested_action: str = Field(min_length=1, max_length=1500)
    uncertainty: str = Field(default="", max_length=1000)
    geography: str = Field(default="", max_length=200)
    priority: SignalPriority = "normal"


class MarineSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    source_name: str
    category: SignalCategory
    title: str
    source_content: str
    summary: str
    why_it_matters: str
    suggested_action: str
    citation_url: str
    published_at: datetime | None
    effective_until: datetime | None
    geography: str
    uncertainty: str
    priority: SignalPriority
    status: Literal["needs_review", "published", "stale", "superseded"]
    reviewed_by: str | None
    reviewed_at: datetime | None
    last_checked_at: datetime
    created_at: datetime
    feedback: SignalFeedbackKind | None = None
    feedback_note: str = ""


class MarineSignalProfileInput(BaseModel):
    service_area: str = Field(default="", max_length=200)
    specialties: list[str] = Field(default_factory=list, max_length=30)
    interests: list[SignalCategory] = Field(default_factory=list, max_length=8)
    digest_email: EmailStr | None = None
    digest_enabled: bool = False

    @field_validator("specialties")
    @classmethod
    def normalize_specialties(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))
        if any(len(value) > 80 for value in normalized):
            raise ValueError("specialties must be at most 80 characters")
        return normalized

    @model_validator(mode="after")
    def digest_needs_recipient(self) -> "MarineSignalProfileInput":
        if self.digest_enabled and self.digest_email is None:
            raise ValueError("digest_email is required when weekly digest is enabled")
        return self


class MarineSignalProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_area: str
    specialties: list[str]
    interests: list[str]
    digest_email: str | None
    digest_enabled: bool
    updated_at: datetime | None = None


class MarineSignalFeedbackInput(BaseModel):
    feedback: SignalFeedbackKind
    note: str = Field(default="", max_length=1000)


class MarineSignalMetrics(BaseModel):
    source_count: int
    fresh_sources: int
    stale_sources: int
    needs_review: int
    citation_coverage: float
    useful_feedback: int
    acted_feedback: int
    feedback_count: int
