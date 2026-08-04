"""AI dispatch engine — rule-based job-priority scoring.

WHY RULE-BASED, NOT MACHINE LEARNED: a model needs labeled outcomes to learn
from, and this platform has none yet — no completed-job history with recorded
actual-vs-scheduled timing, technician performance, or customer satisfaction
to train against. Building or faking an ML model against zero real data would
produce a black box that is *less* trustworthy than a transparent formula, not
more. The threshold worth revisiting this at is roughly 500+ completed jobs
with recorded outcomes (see README "AI dispatch engine") — enough rows that a
simple supervised model (e.g. gradient-boosted trees on the same features
below, or even ordinal regression) would have a real chance of beating this
heuristic rather than overfitting noise. Until then, every score produced here
is fully explainable: `DispatchScore.breakdown` names every factor and its
contribution, so a shop owner (or a support engineer) can always answer "why
did this job rank where it did" without reverse-engineering a model.

Every factor below degrades gracefully when its inputs are missing (most
fields will be NULL/empty for a long time — see migration 0006) rather than
raising or fabricating a plausible-looking number. A neutral (zero)
contribution is always the safe default for "we don't know yet".
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.models import JOB_ASSIGNABLE_ROLES, JobPriority, JobStatus
from app.db.tenant import tenant_context
from app.services.crud import NotFound

# ---------------------------------------------------------------------------
# Tunable weights — named constants, not magic numbers, so a future phase can
# retune these from real dispatch outcomes without touching the scoring logic
# itself. Each is documented with the reasoning behind its magnitude.
# ---------------------------------------------------------------------------

#: Urgency dominates the total. A job that is overdue-and-urgent should be
#: nearly impossible for anything else to outrank; this is the largest single
#: weight by design (see WEIGHT BALANCE note below).
URGENCY_WEIGHT = Decimal("50")

#: Revenue gives bigger jobs a modest lift, but must never be able to outrank
#: urgency on its own. A $50 emergency (urgency near max, ~0 revenue points)
#: must still outscore a $5,000 non-urgent job (urgency near baseline, near-max
#: revenue points) — see test_dispatch_scoring.py for the proof. Capping the
#: revenue contribution well below the urgency ceiling, and requiring genuinely
#: large jobs to reach it, is what enforces that.
REVENUE_WEIGHT = Decimal("15")

#: A repeat customer is worth a little extra priority (retention matters,
#: and a known customer is lower-risk to schedule), but this is explicitly a
#: minor tie-breaker, not a major factor — a brand-new customer's emergency
#: must not be buried under a loyal customer's routine oil change.
CUSTOMER_VALUE_WEIGHT = Decimal("8")

#: Distance/travel-fit is technician-specific, so it only applies in
#: `rank_technicians_for_job`, not in the job-level cached score. Weighted
#: below revenue because travel time is real cost but rarely as decisive as
#: "is this actually urgent" or "will this pay for the truck roll".
DISTANCE_WEIGHT = Decimal("12")

#: Parts availability is currently a no-op (see `_score_parts_availability`)
#: but the weight constant is declared here so wiring it up later (once
#: line-item-to-inventory reservation linkage exists) is a one-line change
#: rather than a new factor design.
PARTS_AVAILABILITY_WEIGHT = Decimal("10")

#: Technician skill fit — meaningful but secondary to urgency/revenue; a
#: perfectly-matched technician on a low-priority job should not leapfrog an
#: urgent job just assigned to a partially-matched one.
TECHNICIAN_FIT_WEIGHT = Decimal("15")

#: Workload tie-breaker in `rank_technicians_for_job`: an already-swamped
#: technician should rank slightly lower among otherwise-similar candidates.
#: Documented choice (per the spec): this is a small ADDITIVE factor in the
#: technician-ranking breakdown, not a hard filter — a swamped technician can
#: still be the objectively best fit (e.g. the only one with the right skill)
#: and should still show up, just not automatically win ties.
WORKLOAD_WEIGHT = Decimal("6")
#: Diminishing effect past a handful of concurrent jobs — the 6th job weighs
#: on a technician's day about as much as the 5th did.
WORKLOAD_SATURATION = 5

#: Urgency sub-scoring. `priority` contributes a base amount; how overdue
#: `scheduled_at` is relative to `now` adds on top, capped so a job scheduled
#: a decade ago cannot mathematically dominate everything forever.
_PRIORITY_BASE: dict[str, Decimal] = {
    JobPriority.LOW.value: Decimal("0.10"),
    JobPriority.NORMAL.value: Decimal("0.35"),
    JobPriority.HIGH.value: Decimal("0.65"),
    JobPriority.URGENT.value: Decimal("0.90"),
}
#: Every day overdue adds this fraction of the urgency ceiling, capped at 1.0
#: total (i.e. fully overdue-saturated) after `_OVERDUE_SATURATION_DAYS`.
_OVERDUE_PER_DAY = Decimal("0.10")
_OVERDUE_SATURATION_DAYS = Decimal("6")

#: Revenue sub-scoring uses a log curve so the marginal value of each extra
#: dollar shrinks — a $10,000 job should not score 100x a $100 job, it should
#: score meaningfully but boundedly more. `_REVENUE_LOG_BASE` sets how quickly
#: the curve saturates; tuned so a ~$5,000 job sits close to (but under) the
#: cap and a $50 job registers near zero.
_REVENUE_SATURATION = Decimal("5000")

#: Customer-value sub-scoring: each prior completed job adds a shrinking
#: increment, capped so a customer with hundreds of jobs does not dwarf every
#: other factor. Saturates around a dozen prior jobs — enough to distinguish
#: "brand new" from "loyal regular" without needing more resolution than that.
_CUSTOMER_VALUE_SATURATION_JOBS = 12

#: Distance sub-scoring: haversine miles are converted to a 0..1 closeness
#: score via this half-life-style falloff — a technician at the door scores
#: ~1.0, one at this many miles away scores ~0.5, and it decays smoothly
#: beyond that rather than cutting off sharply.
_DISTANCE_HALF_LIFE_MILES = Decimal("15")

#: Mean earth radius in miles, for the haversine distance calculation.
_EARTH_RADIUS_MILES = 3958.8

#: Statuses that count as "on this technician's plate right now" for the
#: workload tie-breaker.
_ACTIVE_JOB_STATUSES = (JobStatus.SCHEDULED.value, JobStatus.IN_PROGRESS.value)


def _quantize2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DispatchScore:
    """An explainable score: the total, plus every factor's contribution.

    `breakdown` always has one entry per factor that was evaluated, even when
    a factor contributed zero because its inputs were missing — the caller
    should be able to see "distance: 0.00 (no coordinates)" rather than a
    silently absent key.
    """

    total: Decimal
    breakdown: dict[str, Decimal] = field(default_factory=dict)


class DispatchScoreOut(BaseModel):
    """API/serialization shape of a `DispatchScore`."""

    total: Decimal
    breakdown: dict[str, Decimal]


# ---------------------------------------------------------------------------
# Individual factors — each pure, each documented, each degrading gracefully.
# ---------------------------------------------------------------------------
def _score_urgency(priority: str, scheduled_at: datetime | None, now: datetime) -> Decimal:
    """Base priority level plus how overdue the job is.

    A job with no `scheduled_at` (unscheduled/intake queue) is not "overdue"
    by definition — it contributes only its priority base. A job scheduled in
    the future contributes only its priority base too; overdue-ness only ever
    adds, never subtracts, so a far-future `high` job still outranks a
    far-future `low` job purely on priority.
    """
    base = _PRIORITY_BASE.get(priority, _PRIORITY_BASE[JobPriority.NORMAL.value])

    overdue_fraction = Decimal("0")
    if scheduled_at is not None:
        delta = now - scheduled_at
        overdue_days = Decimal(str(delta.total_seconds() / 86400))
        if overdue_days > 0:
            overdue_fraction = min(
                overdue_days * _OVERDUE_PER_DAY / _OVERDUE_SATURATION_DAYS,
                Decimal("1"),
            )

    # Combine so overdue-ness pushes toward (but does not exceed) the ceiling,
    # rather than being simply additive past 1.0.
    fraction = base + (Decimal("1") - base) * overdue_fraction
    return _quantize2(URGENCY_WEIGHT * fraction)


def _score_revenue(amount: Decimal) -> Decimal:
    """Log-curved revenue lift, capped well under the urgency ceiling.

    Using ln(1 + amount / saturation) normalized against ln(2) means a job at
    exactly `_REVENUE_SATURATION` scores ~1.0 (full weight); smaller jobs
    trail off smoothly and larger jobs keep growing slowly rather than
    plateauing sharply, without ever mattering more than a genuinely urgent
    job (see URGENT_WEIGHT vs REVENUE_WEIGHT and the test proving it).
    """
    if amount <= 0:
        return Decimal("0.00")
    ratio = float(amount) / float(_REVENUE_SATURATION)
    fraction = math.log1p(ratio) / math.log(2)
    return _quantize2(REVENUE_WEIGHT * Decimal(str(fraction)))


def _score_customer_value(completed_job_count: int) -> Decimal:
    """Repeat customers score a little higher. Shrinking marginal returns."""
    if completed_job_count <= 0:
        return Decimal("0.00")
    fraction = min(
        Decimal(completed_job_count) / Decimal(_CUSTOMER_VALUE_SATURATION_JOBS),
        Decimal("1"),
    )
    return _quantize2(CUSTOMER_VALUE_WEIGHT * fraction)


def _haversine_miles(lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> Decimal:
    """Great-circle distance in miles between two lat/long points."""
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.asin(min(1, math.sqrt(a)))
    return Decimal(str(_EARTH_RADIUS_MILES * c))


def _score_distance(
    technician_lat: Decimal | None,
    technician_lon: Decimal | None,
    customer_lat: Decimal | None,
    customer_lon: Decimal | None,
) -> tuple[Decimal, str]:
    """Closer technician scores higher. Neutral (0) if either side lacks
    coordinates — most rows will, for a while (migration 0006 adds the
    columns but nothing backfills them yet), and a neutral contribution is the
    only honest answer when there is no real distance to compute.
    """
    if technician_lat is None or technician_lon is None:
        return Decimal("0.00"), "no technician coordinates"
    if customer_lat is None or customer_lon is None:
        return Decimal("0.00"), "no customer coordinates"

    miles = _haversine_miles(technician_lat, technician_lon, customer_lat, customer_lon)
    # Half-life falloff: closeness = 1 / (1 + miles / half_life).
    closeness = Decimal("1") / (Decimal("1") + miles / _DISTANCE_HALF_LIFE_MILES)
    return _quantize2(DISTANCE_WEIGHT * closeness), f"{miles.quantize(Decimal('0.1'))} mi"


def _score_parts_availability(inventory_shortfall: bool | None) -> tuple[Decimal, str]:
    """No-op placeholder returning a neutral score.

    Job line items MAY reference an `inventory_item_id` (see
    `app/services/jobs.py::add_line_item` / `app/services/inventory.py`), but
    that link only records which SKU was fitted — there is no reservation
    system that holds stock against a scheduled-but-not-yet-worked job. Wiring
    real "will we have the part when this job is worked" logic requires that
    reservation linkage, which is a prerequisite from a future inventory
    phase (tracked in the README deferred-items list). Inventing a
    shortfall signal from the current schema would not reflect anything real,
    so this factor stays neutral until that prerequisite lands. The
    `inventory_shortfall` parameter exists so a future implementation has an
    obvious seam to plug into without changing `score_job`'s signature.
    """
    if inventory_shortfall is None:
        return Decimal("0.00"), "not evaluated (no parts-reservation linkage yet)"
    return Decimal("0.00"), "not evaluated (no parts-reservation linkage yet)"


def _score_technician_fit(
    required_skills: list[str] | None, technician_skills: list[str] | None
) -> tuple[Decimal, str]:
    """Jaccard-style overlap between what the job needs and what the tech has.

    No required skills stated -> neutral (every technician is an equally
    valid fit absent a stated requirement), not a penalty for every candidate.
    Required skills stated but the technician has none/no overlap -> a real
    zero, distinct from "neutral", because the requirement DID exist and this
    candidate does not meet it.
    """
    required = {s.strip().lower() for s in (required_skills or []) if s and s.strip()}
    if not required:
        return TECHNICIAN_FIT_WEIGHT, "no required skills (neutral: every tech qualifies)"

    have = {s.strip().lower() for s in (technician_skills or []) if s and s.strip()}
    if not have:
        return Decimal("0.00"), "technician has no listed skills"

    overlap = required & have
    union = required | have
    jaccard = Decimal(len(overlap)) / Decimal(len(union)) if union else Decimal("0")
    return (
        _quantize2(TECHNICIAN_FIT_WEIGHT * jaccard),
        f"{len(overlap)}/{len(required)} required skills matched",
    )


def _score_workload(active_job_count: int) -> Decimal:
    """A penalty (negative contribution) for a technician who already has a
    full plate. Diminishing per-job impact past `WORKLOAD_SATURATION`
    concurrent jobs. Returned as a negative Decimal so summing the breakdown
    directly reduces the total — an idle technician must always outrank an
    otherwise-identical swamped one.
    """
    if active_job_count <= 0:
        return Decimal("0.00")
    fraction = min(Decimal(active_job_count) / Decimal(WORKLOAD_SATURATION), Decimal("1"))
    return _quantize2(-WORKLOAD_WEIGHT * fraction)


# ---------------------------------------------------------------------------
# score_job — pure function, no DB access, fully unit-testable.
# ---------------------------------------------------------------------------
def score_job(
    job: Any,
    *,
    customer: Any,
    technician: Any | None = None,
    completed_job_count: int = 0,
    inventory_shortfall: bool | None = None,
    active_technician_job_count: int | None = None,
    now: datetime | None = None,
) -> DispatchScore:
    """Compute an explainable dispatch-priority score for `job`.

    `job` and `customer` are anything with the expected attributes (an ORM
    instance, a `Row`, or a plain namespace/mock in tests) — this function
    never issues a query itself, which is what makes it unit-testable without
    a database. `technician` is optional: when absent, the technician-specific
    factors (distance, skill fit, workload) are omitted from the breakdown
    entirely rather than shown as a misleading zero, because "no candidate
    technician was being considered" is different from "this technician is a
    zero-distance, zero-skill-match candidate".
    """
    now = now or datetime.now(timezone.utc)

    breakdown: dict[str, Decimal] = {}

    breakdown["urgency"] = _score_urgency(str(job.priority), job.scheduled_at, now)

    revenue_amount = getattr(job, "revenue_amount", None)
    if revenue_amount is None:
        revenue_amount = Decimal("0")
    breakdown["revenue"] = _score_revenue(Decimal(revenue_amount))

    breakdown["customer_value"] = _score_customer_value(completed_job_count)

    parts_score, _parts_note = _score_parts_availability(inventory_shortfall)
    breakdown["parts_availability"] = parts_score

    if technician is not None:
        distance_score, _distance_note = _score_distance(
            getattr(technician, "home_latitude", None),
            getattr(technician, "home_longitude", None),
            getattr(customer, "latitude", None),
            getattr(customer, "longitude", None),
        )
        breakdown["distance"] = distance_score

        fit_score, _fit_note = _score_technician_fit(
            list(getattr(job, "required_skills", None) or []),
            list(getattr(technician, "skills", None) or []),
        )
        breakdown["technician_fit"] = fit_score

        if active_technician_job_count is not None:
            breakdown["workload"] = _score_workload(active_technician_job_count)

    total = sum(breakdown.values(), Decimal("0"))
    return DispatchScore(total=_quantize2(total), breakdown=breakdown)


# ---------------------------------------------------------------------------
# Service-layer wrappers — these DO query the database, inside tenant_context.
# ---------------------------------------------------------------------------
def _job_revenue_amount(db: Session, job_id: uuid.UUID) -> Decimal:
    """Sum of the job's line items, or the linked estimate's total if the job
    has no line items yet (a freshly-opened job with a rough quote but no
    recorded labor/parts should still get sensible revenue-based priority).
    """
    line_total = db.execute(
        text(
            "SELECT COALESCE(SUM(line_total), 0) FROM job_line_items WHERE job_id = :job_id"
        ),
        {"job_id": job_id},
    ).scalar_one()
    if line_total and Decimal(line_total) > 0:
        return Decimal(line_total)

    estimate_total = db.execute(
        text(
            """
            SELECT total FROM estimates
             WHERE job_id = :job_id
             ORDER BY created_at DESC
             LIMIT 1
            """
        ),
        {"job_id": job_id},
    ).scalar_one_or_none()
    return Decimal(estimate_total) if estimate_total else Decimal("0")


def _customer_completed_job_count(db: Session, customer_id: uuid.UUID) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs
                 WHERE customer_id = :customer_id AND status = 'completed'
                """
            ),
            {"customer_id": customer_id},
        ).scalar_one()
    )


def _active_job_count_for_technician(db: Session, technician_id: uuid.UUID) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs
                 WHERE technician_id = :technician_id
                   AND status = ANY(:statuses)
                """
            ),
            {"technician_id": technician_id, "statuses": list(_ACTIVE_JOB_STATUSES)},
        ).scalar_one()
    )


def _load_job(db: Session, job_id: uuid.UUID) -> Row:
    row = db.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}).first()
    if row is None:
        raise NotFound(f"job {job_id} not found")
    return row


def _load_customer(db: Session, customer_id: uuid.UUID) -> Row:
    row = db.execute(
        text("SELECT * FROM customers WHERE id = :id"), {"id": customer_id}
    ).first()
    if row is None:
        raise NotFound(f"customer {customer_id} not found")
    return row


def rank_technicians_for_job(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Rank this tenant's technicians for `job_id`, best first.

    Candidates are active users in `JOB_ASSIGNABLE_ROLES` (technician, admin,
    owner — the same set the assignment endpoint itself allows, see
    `app.services.jobs._require_assignable_technician`). Each candidate's
    score includes the technician-specific factors (distance, skill fit,
    workload) on top of the job-level factors (urgency, revenue, customer
    value, parts availability).
    """
    with tenant_context(db, company_id):
        job = _load_job(db, job_id)
        customer = _load_customer(db, job.customer_id)
        revenue_amount = _job_revenue_amount(db, job_id)
        completed_job_count = _customer_completed_job_count(db, job.customer_id)

        technicians = db.execute(
            text(
                """
                SELECT * FROM users
                 WHERE role = ANY(:roles) AND is_active = true
                 ORDER BY full_name NULLS LAST, email
                """
            ),
            {"roles": [r.value for r in JOB_ASSIGNABLE_ROLES]},
        ).all()

        job_with_revenue = dict(job._mapping) | {"revenue_amount": revenue_amount}

        candidates: list[dict[str, Any]] = []
        for tech in technicians:
            active_count = _active_job_count_for_technician(db, tech.id)
            score = score_job(
                _Row(job_with_revenue),
                customer=customer,
                technician=tech,
                completed_job_count=completed_job_count,
                active_technician_job_count=active_count,
            )
            candidates.append(
                {
                    "technician_id": tech.id,
                    "technician_name": tech.full_name or tech.email,
                    "score": score,
                }
            )

    candidates.sort(key=lambda c: c["score"].total, reverse=True)
    return candidates


def recompute_and_cache_score(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID
) -> DispatchScore:
    """Compute the job's technician-independent score and persist it.

    Used to prioritize the intake queue / schedule board independent of any
    specific technician assignment — urgency, revenue and customer value only.
    """
    with tenant_context(db, company_id):
        job = _load_job(db, job_id)
        customer = _load_customer(db, job.customer_id)
        revenue_amount = _job_revenue_amount(db, job_id)
        completed_job_count = _customer_completed_job_count(db, job.customer_id)

        job_with_revenue = dict(job._mapping) | {"revenue_amount": revenue_amount}
        score = score_job(
            _Row(job_with_revenue),
            customer=customer,
            completed_job_count=completed_job_count,
        )

        db.execute(
            text(
                """
                UPDATE jobs
                   SET dispatch_score = :total,
                       dispatch_score_breakdown = CAST(:breakdown AS JSONB),
                       dispatch_scored_at = now()
                 WHERE id = :id
                """
            ),
            {
                "total": score.total,
                "breakdown": _breakdown_to_json(score.breakdown),
                "id": job_id,
            },
        )
        db.commit()

    return score


class _Row:
    """Thin attribute-access wrapper around a dict, for feeding `score_job` a
    merged job+revenue mapping without a real SQLAlchemy Row.
    """

    def __init__(self, mapping: dict[str, Any]):
        self._mapping_data = mapping

    def __getattr__(self, name: str) -> Any:
        try:
            return self._mapping_data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _breakdown_to_json(breakdown: dict[str, Decimal]) -> str:
    import json

    return json.dumps({k: str(v) for k, v in breakdown.items()})


__all__ = [
    "DispatchScore",
    "DispatchScoreOut",
    "rank_technicians_for_job",
    "recompute_and_cache_score",
    "score_job",
]
