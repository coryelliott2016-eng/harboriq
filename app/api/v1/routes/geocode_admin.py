"""On-demand geocoding backfill for the caller's tenant (`require_admin`).

See `app/jobs/geocode_backfill.py` for the all-tenants cron entry point
(`python -m app.jobs.geocode_backfill`) that this route's logic is shared
with — this is the same backfill, scoped to one company, for an admin who
does not want to wait for a scheduled run (same relationship as
`POST /billing/dunning/run` to `python -m app.jobs.dunning_sweep`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_admin
from app.jobs.geocode_backfill import backfill_company
from app.schemas.geocoding import GeocodeBackfillResponse

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.post("/geocode-backfill", response_model=GeocodeBackfillResponse)
def run_geocode_backfill(
    force: bool = False,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Geocode this tenant's customers/users that have an address but no
    coordinates yet.

    `force=true` re-geocodes every addressed row regardless of existing
    coordinates (e.g. after switching geocoding providers); the default
    only touches rows that have never been geocoded, so re-running this
    endpoint is always safe.
    """
    result = backfill_company(db, company_id, force=force)
    return GeocodeBackfillResponse(**result)
