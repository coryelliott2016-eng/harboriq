"""Field-app endpoints (Phase 12): job attachments (photos/signatures) and the
per-job time clock.

Authorization mirrors `jobs.py`'s line-item endpoints exactly: office staff
act on any job, the assigned technician only on jobs assigned to them, via
the same `authorize_job_action` dependency. These routes are additive to the
existing `/jobs` router rather than folded into `jobs.py` itself, keeping
this phase's diff to `jobs.py` at zero.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import authorize_job_action, get_current_company_id, get_current_user, get_db
from app.api.errors import http_errors
from app.schemas.field_app import (
    ClockActionRequest,
    JobAttachmentCreate,
    JobAttachmentOut,
    JobTimeEntryOut,
)
from app.services import field_app as service
from app.services.auth import AuthenticatedUser

router = APIRouter(prefix="/jobs", tags=["field-app"])


# ---------------------------------------------------------------------------
# attachments — photos and digital signatures
# ---------------------------------------------------------------------------
@router.post(
    "/{job_id}/attachments",
    response_model=JobAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_attachment(
    job_id: uuid.UUID,
    body: JobAttachmentCreate,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Attach a photo or digital signature to a job.

    Safe to retry: a repeated call carrying the same `idempotency_key`
    returns the original attachment instead of creating a duplicate — the
    offline-sync queue relies on this when replaying a queued capture after
    connectivity returns.
    """
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.add_attachment(
            db, user.company_id, job_id, user.id, body.model_dump()
        )


@router.get("/{job_id}/attachments", response_model=list[JobAttachmentOut])
def list_attachments(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.list_attachments(db, company_id, job_id)


# ---------------------------------------------------------------------------
# time clock
# ---------------------------------------------------------------------------
@router.post(
    "/{job_id}/clock-in",
    response_model=JobTimeEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def clock_in(
    job_id: uuid.UUID,
    body: ClockActionRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Clock the caller in on this job. 409 if already clocked in (unless
    this is an idempotent replay of the same queued action)."""
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.clock_in(
            db,
            user.company_id,
            job_id,
            user.id,
            body.idempotency_key,
            client_queued_at=body.client_queued_at,
        )


@router.post("/{job_id}/clock-out", response_model=JobTimeEntryOut)
def clock_out(
    job_id: uuid.UUID,
    body: ClockActionRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Clock the caller out of this job. 422 if not currently clocked in."""
    authorize_job_action(db, user, job_id)
    with http_errors():
        return service.clock_out(
            db,
            user.company_id,
            job_id,
            user.id,
            body.idempotency_key,
            client_queued_at=body.client_queued_at,
        )


@router.get("/{job_id}/time-entries", response_model=list[JobTimeEntryOut])
def list_time_entries(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.list_time_entries(db, company_id, job_id)
