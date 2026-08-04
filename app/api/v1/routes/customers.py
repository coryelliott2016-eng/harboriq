"""Customer endpoints.

Reads are open to any authenticated user — a technician on a job needs the
owner's phone number. Writes are restricted to owner/admin/office, because the
customer book is front-desk work.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.customers import CustomerCreate, CustomerOut, CustomerUpdate
from app.schemas.portal import PortalInviteOut
from app.schemas.vessels import VesselOut
from app.services import customers as service
from app.services import portal as portal_service
from app.services import vessels as vessels_service
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_customer(
    body: CustomerCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.create(db, company_id, body.model_dump())


@router.get("", response_model=list[CustomerOut])
def list_customers(
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """List the tenant's customers. `search` matches name, email or phone."""
    return service.list_customers(
        db, company_id, search=search, limit=limit, offset=offset
    )


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, customer_id)


@router.get("/{customer_id}/vessels", response_model=list[VesselOut])
def list_customer_vessels(
    customer_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """The customer's fleet. 404s for an unknown customer rather than []."""
    with http_errors():
        service.get(db, company_id, customer_id)
        return vessels_service.list_vessels(
            db, company_id, customer_id=customer_id, limit=limit, offset=offset
        )


@router.patch(
    "/{customer_id}",
    response_model=CustomerOut,
    dependencies=[Depends(require_operations)],
)
def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.update(
            db, company_id, customer_id, body.model_dump(exclude_unset=True)
        )


@router.post(
    "/{customer_id}/portal-invite",
    response_model=PortalInviteOut,
    dependencies=[Depends(require_operations)],
)
def send_portal_invite(
    customer_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Issue (or renew) the customer's durable portal magic link and email it
    to them, mirroring `POST /invoices/{id}/send`'s issue-token + outbox
    pattern. Safe to call again later to renew an expiring/expired link."""
    with http_errors():
        event_id = portal_service.send_portal_invite(db, company_id, customer_id)
    dispatch_outbox_soon(background_tasks)
    return PortalInviteOut(customer_id=customer_id, outbox_event_id=event_id)


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operations)],
)
def delete_customer(
    customer_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Delete a customer. 409 while vessels or jobs still reference them."""
    with http_errors():
        service.delete(db, company_id, customer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
