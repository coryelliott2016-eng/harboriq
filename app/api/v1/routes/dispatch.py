"""AI dispatch engine endpoints.

Everything here is `require_operations`-gated: deciding who gets dispatched
where is shop-management work (owner/admin/office), the same tier that
already creates and assigns jobs in `app.api.v1.routes.jobs`. A technician can
still see the *result* of dispatch (their own assigned jobs, via the existing
job endpoints) but does not get to browse candidate rankings for jobs that
are not theirs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.dispatch import DispatchCandidateOut, JobDispatchScoreOut
from app.services import dispatch as service

router = APIRouter(prefix="/jobs", tags=["dispatch"])


@router.get(
    "/{job_id}/dispatch/candidates",
    response_model=list[DispatchCandidateOut],
    dependencies=[Depends(require_operations)],
)
def get_dispatch_candidates(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Rank this tenant's technicians for `job_id`, best first.

    See `app.services.dispatch.rank_technicians_for_job` for the scoring
    factors (urgency, revenue, customer value, distance, parts availability,
    technician skill fit, current workload) and why each degrades gracefully
    rather than erroring when its inputs are missing.
    """
    with http_errors():
        candidates = service.rank_technicians_for_job(db, company_id, job_id)
    return [
        {
            "technician_id": c["technician_id"],
            "technician_name": c["technician_name"],
            "score": {"total": c["score"].total, "breakdown": c["score"].breakdown},
        }
        for c in candidates
    ]


@router.post(
    "/{job_id}/dispatch/recompute",
    response_model=JobDispatchScoreOut,
    dependencies=[Depends(require_operations)],
)
def recompute_dispatch_score(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Recompute and persist the job's technician-independent dispatch score.

    Called after anything that could change urgency/revenue/customer-value
    inputs (e.g. line items added, priority changed) so the cached
    `jobs.dispatch_score` used by `GET /jobs?sort=priority_score` stays fresh.
    """
    with http_errors():
        score = service.recompute_and_cache_score(db, company_id, job_id)
    return {
        "job_id": job_id,
        "dispatch_score": score.total,
        "dispatch_score_breakdown": score.breakdown,
        "dispatch_scored_at": None,  # set by DB `now()`; caller can GET the job for it
    }
