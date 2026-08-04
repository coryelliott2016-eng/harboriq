"""Unit tests for `app.services.dispatch.score_job` — pure function, no DB.

These are the tests that prove the weight-balance claims documented as
comments in `app/services/dispatch.py`: urgency must dominate revenue,
distance/skill-fit must degrade gracefully rather than error, and customer
value must be a real (queried) signal rather than a stub.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.dispatch import score_job


def _job(
    priority="normal",
    scheduled_at=None,
    revenue_amount=Decimal("0"),
    required_skills=None,
):
    return SimpleNamespace(
        priority=priority,
        scheduled_at=scheduled_at,
        revenue_amount=revenue_amount,
        required_skills=required_skills or [],
    )


def _customer(latitude=None, longitude=None):
    return SimpleNamespace(latitude=latitude, longitude=longitude)


def _technician(home_latitude=None, home_longitude=None, skills=None):
    return SimpleNamespace(
        home_latitude=home_latitude, home_longitude=home_longitude, skills=skills or []
    )


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Urgency must dominate revenue
# ---------------------------------------------------------------------------
def test_a_cheap_emergency_outscores_an_expensive_non_urgent_job():
    """The core weight-balance claim in the spec: a $50 emergency must beat a
    $5,000 non-urgent job. Revenue gives a lift, but urgency is the trump
    card."""
    emergency = score_job(
        _job(priority="urgent", revenue_amount=Decimal("50")),
        customer=_customer(),
        now=NOW,
    )
    big_non_urgent = score_job(
        _job(priority="low", revenue_amount=Decimal("5000")),
        customer=_customer(),
        now=NOW,
    )
    assert emergency.total > big_non_urgent.total


def test_urgent_priority_scores_higher_than_low_priority_all_else_equal():
    urgent = score_job(_job(priority="urgent"), customer=_customer(), now=NOW)
    low = score_job(_job(priority="low"), customer=_customer(), now=NOW)
    assert urgent.total > low.total
    assert urgent.breakdown["urgency"] > low.breakdown["urgency"]


def test_an_overdue_job_scores_higher_than_the_same_job_on_time():
    on_time = score_job(
        _job(priority="normal", scheduled_at=NOW), customer=_customer(), now=NOW
    )
    overdue = score_job(
        _job(priority="normal", scheduled_at=NOW - timedelta(days=10)),
        customer=_customer(),
        now=NOW,
    )
    assert overdue.breakdown["urgency"] > on_time.breakdown["urgency"]


def test_a_future_scheduled_job_is_not_penalised_for_being_in_the_future():
    future = score_job(
        _job(priority="normal", scheduled_at=NOW + timedelta(days=30)),
        customer=_customer(),
        now=NOW,
    )
    on_time = score_job(
        _job(priority="normal", scheduled_at=NOW), customer=_customer(), now=NOW
    )
    assert future.breakdown["urgency"] == on_time.breakdown["urgency"]


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------
def test_revenue_increases_monotonically_but_with_diminishing_returns():
    cheap = score_job(_job(revenue_amount=Decimal("100")), customer=_customer(), now=NOW)
    mid = score_job(_job(revenue_amount=Decimal("1000")), customer=_customer(), now=NOW)
    expensive = score_job(
        _job(revenue_amount=Decimal("10000")), customer=_customer(), now=NOW
    )
    assert cheap.breakdown["revenue"] < mid.breakdown["revenue"] < expensive.breakdown[
        "revenue"
    ]
    # Diminishing returns on a logarithmic curve show up as a shrinking
    # jump-per-dollar over equally-sized absolute intervals, not a shrinking
    # absolute jump over intervals of wildly different size (a $9,000 jump
    # naturally adds more raw points than a $900 jump even on a log curve).
    # Compare two $900 intervals instead: 100->1000 and 9100->10000.
    upper = score_job(_job(revenue_amount=Decimal("9100")), customer=_customer(), now=NOW)
    top = score_job(_job(revenue_amount=Decimal("10000")), customer=_customer(), now=NOW)
    lower_interval_jump = mid.breakdown["revenue"] - cheap.breakdown["revenue"]
    upper_interval_jump = top.breakdown["revenue"] - upper.breakdown["revenue"]
    assert lower_interval_jump > upper_interval_jump


def test_zero_revenue_contributes_nothing():
    scored = score_job(_job(revenue_amount=Decimal("0")), customer=_customer(), now=NOW)
    assert scored.breakdown["revenue"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Customer value
# ---------------------------------------------------------------------------
def test_customer_value_increases_with_more_completed_jobs():
    new_customer = score_job(
        _job(), customer=_customer(), completed_job_count=0, now=NOW
    )
    loyal_customer = score_job(
        _job(), customer=_customer(), completed_job_count=10, now=NOW
    )
    assert loyal_customer.breakdown["customer_value"] > new_customer.breakdown[
        "customer_value"
    ]


def test_customer_value_saturates_rather_than_growing_unbounded():
    a_lot = score_job(_job(), customer=_customer(), completed_job_count=50, now=NOW)
    even_more = score_job(
        _job(), customer=_customer(), completed_job_count=500, now=NOW
    )
    assert a_lot.breakdown["customer_value"] == even_more.breakdown["customer_value"]


# ---------------------------------------------------------------------------
# Distance — graceful degradation
# ---------------------------------------------------------------------------
def test_distance_is_neutral_when_technician_has_no_coordinates():
    scored = score_job(
        _job(),
        customer=_customer(latitude=Decimal("27.33"), longitude=Decimal("-82.53")),
        technician=_technician(),  # no home coordinates
        now=NOW,
    )
    assert scored.breakdown["distance"] == Decimal("0.00")


def test_distance_is_neutral_when_customer_has_no_coordinates():
    scored = score_job(
        _job(),
        customer=_customer(),  # no coordinates
        technician=_technician(
            home_latitude=Decimal("27.33"), home_longitude=Decimal("-82.53")
        ),
        now=NOW,
    )
    assert scored.breakdown["distance"] == Decimal("0.00")


def test_a_closer_technician_scores_higher_than_a_farther_one():
    # Sarasota, FL customer.
    customer = _customer(latitude=Decimal("27.3364"), longitude=Decimal("-82.5307"))
    close_tech = _technician(
        home_latitude=Decimal("27.3400"), home_longitude=Decimal("-82.5300")
    )
    # Tampa, ~40 miles north.
    far_tech = _technician(
        home_latitude=Decimal("27.9506"), home_longitude=Decimal("-82.4572")
    )

    close_score = score_job(_job(), customer=customer, technician=close_tech, now=NOW)
    far_score = score_job(_job(), customer=customer, technician=far_tech, now=NOW)

    assert close_score.breakdown["distance"] > far_score.breakdown["distance"]


def test_distance_factor_is_absent_when_no_technician_is_given():
    scored = score_job(_job(), customer=_customer(), now=NOW)
    assert "distance" not in scored.breakdown
    assert "technician_fit" not in scored.breakdown


# ---------------------------------------------------------------------------
# Technician skill fit
# ---------------------------------------------------------------------------
def test_skill_fit_is_neutral_and_maximal_when_job_requires_no_skills():
    scored = score_job(
        _job(required_skills=[]),
        customer=_customer(),
        technician=_technician(skills=[]),
        now=NOW,
    )
    from app.services.dispatch import TECHNICIAN_FIT_WEIGHT

    assert scored.breakdown["technician_fit"] == TECHNICIAN_FIT_WEIGHT


def test_skill_fit_rewards_overlap_between_required_and_held_skills():
    perfect_match = score_job(
        _job(required_skills=["outboard", "electrical"]),
        customer=_customer(),
        technician=_technician(skills=["outboard", "electrical"]),
        now=NOW,
    )
    no_match = score_job(
        _job(required_skills=["outboard", "electrical"]),
        customer=_customer(),
        technician=_technician(skills=["upholstery"]),
        now=NOW,
    )
    partial_match = score_job(
        _job(required_skills=["outboard", "electrical"]),
        customer=_customer(),
        technician=_technician(skills=["outboard"]),
        now=NOW,
    )
    assert perfect_match.breakdown["technician_fit"] > partial_match.breakdown[
        "technician_fit"
    ] > no_match.breakdown["technician_fit"]
    assert no_match.breakdown["technician_fit"] == Decimal("0.00")


def test_skill_fit_is_zero_when_required_skills_exist_but_technician_has_none():
    scored = score_job(
        _job(required_skills=["outboard"]),
        customer=_customer(),
        technician=_technician(skills=[]),
        now=NOW,
    )
    assert scored.breakdown["technician_fit"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Parts availability — documented no-op
# ---------------------------------------------------------------------------
def test_parts_availability_is_always_neutral_today():
    with_shortfall = score_job(
        _job(), customer=_customer(), inventory_shortfall=True, now=NOW
    )
    without_shortfall = score_job(
        _job(), customer=_customer(), inventory_shortfall=False, now=NOW
    )
    unspecified = score_job(_job(), customer=_customer(), now=NOW)
    assert (
        with_shortfall.breakdown["parts_availability"]
        == without_shortfall.breakdown["parts_availability"]
        == unspecified.breakdown["parts_availability"]
        == Decimal("0.00")
    )


# ---------------------------------------------------------------------------
# Workload tie-breaker
# ---------------------------------------------------------------------------
def test_a_busier_technician_scores_lower_all_else_equal():
    idle = score_job(
        _job(),
        customer=_customer(),
        technician=_technician(),
        active_technician_job_count=0,
        now=NOW,
    )
    swamped = score_job(
        _job(),
        customer=_customer(),
        technician=_technician(),
        active_technician_job_count=8,
        now=NOW,
    )
    assert idle.total > swamped.total


def test_total_is_the_sum_of_the_breakdown():
    scored = score_job(
        _job(priority="high", revenue_amount=Decimal("2000")),
        customer=_customer(),
        technician=_technician(),
        completed_job_count=3,
        active_technician_job_count=1,
        now=NOW,
    )
    assert scored.total == sum(scored.breakdown.values())
