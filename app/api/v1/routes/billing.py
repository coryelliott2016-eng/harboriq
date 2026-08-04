"""Billing administration — Stripe Connect onboarding/status and the
on-demand dunning sweep. Both are owner/admin-only (`require_admin`):
Connect changes where a tenant's money settles, and running dunning sends
customer-facing emails on demand, neither of which office/technician roles
should be able to trigger.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_admin
from app.api.errors import http_errors
from app.schemas.billing import (
    ConnectOnboardingResponse,
    ConnectStatusResponse,
    DunningRunResponse,
)
from app.services import billing as service

router = APIRouter(
    prefix="/billing", tags=["billing"], dependencies=[Depends(require_admin)]
)


@router.post("/connect/onboarding-link", response_model=ConnectOnboardingResponse)
def create_connect_onboarding_link(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Start (or resume) Stripe Connect Standard onboarding for this tenant.

    502 if Stripe is not configured or the API call fails; the tenant keeps
    working on the pre-Connect, single-platform-account path either way.
    """
    with http_errors():
        result = service.start_connect_onboarding(db, company_id)
    return ConnectOnboardingResponse(**result)


@router.get("/connect/status", response_model=ConnectStatusResponse)
def get_connect_status(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """`connected: false` (no Stripe call made) is the normal state for a
    tenant that has never started onboarding — not an error."""
    with http_errors():
        result = service.get_connect_status(db, company_id)
    return ConnectStatusResponse(**result)


@router.post("/dunning/run", response_model=DunningRunResponse)
def run_dunning_sweep(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """On-demand dunning sweep for this tenant only (see also
    `python -m app.jobs.dunning_sweep` for an all-tenants cron entry point).
    """
    with http_errors():
        result = service.run_dunning_sweep(db, company_id)
    return DunningRunResponse(**result)
