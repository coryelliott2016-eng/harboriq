"""Estimate endpoints — staff build, send and convert priced proposals.

Gated behind `require_operations` (owner/admin/office), like invoices: the
`UserRole` docstring assigns "customers, estimates, invoices" to office staff,
and technicians never touch pricing. Customer approval is NOT here — it stays
on the existing portal + `POST /public/estimate/{token}/approve` path.

Status never moves through a generic PATCH: `send` and `convert` are explicit
actions validated by `EstimateSM`, so an illegal move is a 409.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_current_user, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.estimates import (
    EstimateConvertResponse,
    EstimateCreate,
    EstimateDetail,
    EstimateLineItemOut,
    EstimateOut,
    EstimateSendResponse,
)
from app.services import estimates as service
from app.services.auth import AuthenticatedUser
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(
    prefix="/estimates", tags=["estimates"], dependencies=[Depends(require_operations)]
)

EstimateStatus = Literal["draft", "sent", "viewed", "approved", "declined", "expired", "invoiced"]


def _detail(result: dict) -> EstimateDetail:
    detail = EstimateDetail.model_validate(result["estimate"])
    detail.line_items = [EstimateLineItemOut.model_validate(r) for r in result["line_items"]]
    detail.invoice_id = result.get("invoice_id")
    return detail


@router.post("", response_model=EstimateDetail, status_code=status.HTTP_201_CREATED)
def create_estimate(
    body: EstimateCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a `draft` estimate on a job. Diagnostic fees are `fee` lines;
    labor lines accept fractional hours."""
    with http_errors():
        result = service.create_estimate(
            db,
            company_id,
            body.job_id,
            [li.model_dump() for li in body.line_items],
            tax_rate=body.tax_rate,
            notes=body.notes,
            actor_user_id=user.id,
        )
    return _detail(result)


@router.get("", response_model=list[EstimateOut])
def list_estimates(
    estimate_status: EstimateStatus | None = Query(default=None, alias="status"),
    job_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_estimates(
        db, company_id, status=estimate_status, job_id=job_id,
        customer_id=customer_id, limit=limit, offset=offset,
    )


@router.get("/{estimate_id}", response_model=EstimateDetail)
def get_estimate(
    estimate_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        result = service.get_detail(db, company_id, estimate_id)
    return _detail(result)


@router.post("/{estimate_id}/send", response_model=EstimateSendResponse)
def send_estimate(
    estimate_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """`draft -> sent` and email the customer a portal link to review and
    approve. 409 if the estimate is not a draft."""
    with http_errors():
        result = service.send_estimate(db, company_id, estimate_id, actor_user_id=user.id)
    if result["email_queued"]:
        dispatch_outbox_soon(background_tasks)
    return EstimateSendResponse(estimate=result["estimate"], email_queued=result["email_queued"])


@router.post("/{estimate_id}/convert", response_model=EstimateConvertResponse)
def convert_estimate(
    estimate_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """`approved -> invoiced`: create a draft invoice containing exactly the
    approved lines. 409 unless the customer has approved the estimate."""
    with http_errors():
        result = service.convert_to_invoice(db, company_id, estimate_id, actor_user_id=user.id)
    return EstimateConvertResponse(estimate=result["estimate"], invoice_id=result["invoice_id"])
