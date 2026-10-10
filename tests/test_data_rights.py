from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.data_rights import (
    AnalyticsEvent,
    DataCategory,
    DataRights,
    Metric,
    Purpose,
    eligible,
    internal_benchmark_counts,
)

pytestmark = pytest.mark.no_db
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def rights(**changes):
    values = {
        "source": "tenant-work-orders",
        "owner_id": uuid4(),
        "company_id": uuid4(),
        "collected_at": NOW - timedelta(days=1),
        "retain_until": NOW + timedelta(days=30),
        "permitted_purposes": frozenset(Purpose),
        "consent_status": "granted",
        "consent_version": "pilot-v1",
        "rights_checked_at": NOW,
        "category": DataCategory.OPERATIONAL,
    }
    return DataRights(**(values | changes))


@pytest.mark.parametrize("changes", [
    {"consent_status": "unknown"},
    {"consent_status": "revoked"},
    {"consent_version": None},
    {"rights_checked_at": None},
    {"rights_checked_at": NOW + timedelta(seconds=1)},
    {"permitted_purposes": frozenset()},
    {"prohibited_purposes": frozenset({Purpose.INTERNAL_ANALYTICS})},
    {"retain_until": NOW},
    {"license_reference": "commercial-feed-license"},
])
def test_analytics_denies_missing_expired_or_restricted_rights(changes):
    assert not eligible(rights(**changes), Purpose.INTERNAL_ANALYTICS, now=NOW)


@pytest.mark.parametrize("category", [
    DataCategory.FISHING_GROUNDS,
    DataCategory.VESSEL_MOVEMENTS,
    DataCategory.RESTRICTED_AIS,
    DataCategory.CONFIDENTIAL,
    DataCategory.LICENSED_CHART,
    DataCategory.PUBLIC_MARINE,
])
def test_sensitive_and_feed_data_never_enters_benchmarks(category):
    assert not eligible(rights(category=category), Purpose.INTERNAL_ANALYTICS, now=NOW)


def test_tenant_assistance_requires_matching_tenant():
    record = rights()
    assert eligible(record, Purpose.TENANT_ASSISTANCE, now=NOW, company_id=record.company_id)
    assert not eligible(record, Purpose.TENANT_ASSISTANCE, now=NOW, company_id=uuid4())
    assert not eligible(record, Purpose.TENANT_ASSISTANCE, now=NOW)


def test_contact_or_marketing_consent_does_not_grant_referral():
    record = rights()
    assert not eligible(record, Purpose.REFERRAL, now=NOW, company_id=record.company_id)


def test_referral_requires_current_recipient_specific_authorization():
    recipient = uuid4()
    record = rights(
        referral_recipient_id=recipient,
        referral_authorized_until=NOW + timedelta(hours=1),
    )
    args = {"now": NOW, "company_id": record.company_id, "recipient_id": recipient}
    assert eligible(record, Purpose.REFERRAL, **args)
    assert not eligible(record, Purpose.REFERRAL, **(args | {"recipient_id": uuid4()}))
    assert not eligible(record, Purpose.REFERRAL, **(args | {"company_id": uuid4()}))
    assert not eligible(
        record, Purpose.REFERRAL, **(args | {"now": NOW + timedelta(hours=1)})
    )


def event(record=None, metric=Metric.WORK_ORDER_COMPLETED):
    return AnalyticsEvent(record_id=uuid4(), metric=metric, rights=record or rights())


def test_small_groups_suppressed_and_duplicates_do_not_inflate_counts():
    events = [event() for _ in range(4)]
    assert internal_benchmark_counts(events, now=NOW) == {}
    events.append(event())
    assert internal_benchmark_counts(events + events, now=NOW) == {Metric.WORK_ORDER_COMPLETED: 5}


def test_each_cohort_is_suppressed_separately():
    events = [event() for _ in range(5)] + [event(metric=Metric.SLIP_BOOKING_COMPLETED)]
    assert internal_benchmark_counts(events, now=NOW) == {Metric.WORK_ORDER_COMPLETED: 5}


def test_many_records_from_one_business_or_owner_do_not_meet_floor():
    one_company = uuid4()
    assert internal_benchmark_counts(
        [event(rights(company_id=one_company)) for _ in range(10)], now=NOW
    ) == {}
    one_owner = uuid4()
    assert internal_benchmark_counts(
        [event(rights(owner_id=one_owner)) for _ in range(10)], now=NOW
    ) == {}


def test_ineligible_records_do_not_count_toward_threshold():
    events = [event() for _ in range(4)] + [event(rights(consent_status="revoked"))]
    assert internal_benchmark_counts(events, now=NOW) == {}


def test_floor_cannot_be_lowered_and_naive_dates_rejected():
    with pytest.raises(ValueError):
        internal_benchmark_counts([], now=NOW, minimum_contributors=1)
    with pytest.raises(ValueError):
        internal_benchmark_counts([], now=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        rights(retain_until=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        rights(retain_until=NOW - timedelta(days=2))


def test_raw_customer_or_location_fields_are_not_accepted():
    with pytest.raises(ValidationError):
        AnalyticsEvent(record_id=uuid4(), metric=Metric.WORK_ORDER_COMPLETED,
                       rights=rights(), latitude=27.0)
