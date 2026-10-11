"""Internal-only eligibility gates; no tenant records are exported by this module."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Purpose(StrEnum):
    TENANT_ASSISTANCE = "tenant_assistance"
    INTERNAL_ANALYTICS = "internal_analytics"
    REFERRAL = "referral"


class DataCategory(StrEnum):
    OPERATIONAL = "operational"
    PUBLIC_MARINE = "public_marine"
    FISHING_GROUNDS = "fishing_grounds"
    VESSEL_MOVEMENTS = "vessel_movements"
    RESTRICTED_AIS = "restricted_ais"
    CONFIDENTIAL = "confidential"
    LICENSED_CHART = "licensed_chart"


class Metric(StrEnum):
    WORK_ORDER_COMPLETED = "work_order_completed"
    MAINTENANCE_COMPLETED = "maintenance_completed"
    SLIP_BOOKING_COMPLETED = "slip_booking_completed"


class DataRights(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    owner_id: UUID
    company_id: UUID
    collected_at: AwareDatetime
    retain_until: AwareDatetime
    permitted_purposes: frozenset[Purpose] = frozenset()
    consent_status: str = Field(default="unknown", pattern="^(unknown|granted|revoked)$")
    consent_version: str | None = Field(default=None, min_length=1, max_length=64)
    rights_checked_at: AwareDatetime | None = None
    license_reference: str | None = Field(default=None, min_length=1, max_length=200)
    prohibited_purposes: frozenset[Purpose] = frozenset()
    category: DataCategory
    referral_recipient_id: UUID | None = None
    referral_authorized_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_retention(self) -> DataRights:
        if self.retain_until <= self.collected_at:
            raise ValueError("retention must end after collection")
        if self.rights_checked_at is not None and self.rights_checked_at < self.collected_at:
            raise ValueError("rights review cannot precede collection")
        return self


def _aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("an aware current time is required")


def eligible(
    rights: DataRights,
    purpose: Purpose,
    *,
    now: datetime,
    company_id: UUID | None = None,
    recipient_id: UUID | None = None,
) -> bool:
    """Require affirmative, current rights; callers must load metadata from trusted storage."""
    _aware(now)
    if not rights.collected_at <= now < rights.retain_until:
        return False
    if rights.rights_checked_at is None or rights.rights_checked_at > now:
        return False
    if purpose not in rights.permitted_purposes or purpose in rights.prohibited_purposes:
        return False
    if rights.consent_status != "granted" or not rights.consent_version:
        return False
    if purpose == Purpose.INTERNAL_ANALYTICS:
        # Neither public/licensed feeds nor sensitive customer categories enter benchmarks.
        return rights.category == DataCategory.OPERATIONAL and not rights.license_reference
    if company_id is None or company_id != rights.company_id:
        return False
    if purpose == Purpose.REFERRAL:
        return (
            rights.category == DataCategory.OPERATIONAL
            and not rights.license_reference
            and recipient_id is not None
            and recipient_id == rights.referral_recipient_id
            and rights.referral_authorized_until is not None
            and now < rights.referral_authorized_until
        )
    return rights.category in (DataCategory.OPERATIONAL, DataCategory.PUBLIC_MARINE)


class AnalyticsEvent(BaseModel):
    """A pre-minimized operational event, never a customer/location/free-text record."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    metric: Metric
    rights: DataRights


MINIMUM_CONTRIBUTORS = 5


def internal_benchmark_counts(
    events: list[AnalyticsEvent], *, now: datetime, minimum_contributors: int = MINIMUM_CONTRIBUTORS
) -> dict[Metric, int]:
    """Suppress each cohort unless both distinct businesses and owners meet the floor.

    This is not an anonymization guarantee or an external analytics product.
    No endpoint exposes these results; repeated releases need a separate
    disclosure/differencing review before any commercial publication.
    """
    _aware(now)
    if minimum_contributors < MINIMUM_CONTRIBUTORS:
        raise ValueError("the disclosure floor cannot be lowered")
    counts: Counter[Metric] = Counter()
    companies: dict[Metric, set[UUID]] = defaultdict(set)
    owners: dict[Metric, set[UUID]] = defaultdict(set)
    seen: set[tuple[UUID, UUID]] = set()
    for event in events:
        if not eligible(event.rights, Purpose.INTERNAL_ANALYTICS, now=now):
            continue
        key = (event.rights.company_id, event.record_id)
        if key in seen:
            continue
        seen.add(key)
        counts[event.metric] += 1
        companies[event.metric].add(event.rights.company_id)
        owners[event.metric].add(event.rights.owner_id)
    return {
        metric: count
        for metric, count in counts.items()
        if len(companies[metric]) >= minimum_contributors
        and len(owners[metric]) >= minimum_contributors
    }
