"""Vendor endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.vendors import (
    VendorCreate,
    VendorOut,
    VendorStatusUpdate,
    VendorUpdate,
)
from app.services import vendors as service

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.post(
    "",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_vendor(
    body: VendorCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.create(db, company_id, body.model_dump())


@router.get("", response_model=list[VendorOut])
def list_vendors(
    search: str | None = Query(default=None, max_length=200),
    include_inactive: bool = Query(
        default=False,
        description="Include archived (deactivated) vendors in the results.",
    ),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_vendors(
        db, company_id, search=search, include_inactive=include_inactive
    )


@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(
    vendor_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, vendor_id)


@router.patch(
    "/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require_operations)],
)
def update_vendor(
    vendor_id: uuid.UUID,
    body: VendorUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.update(
            db, company_id, vendor_id, body.model_dump(exclude_unset=True)
        )


@router.post(
    "/{vendor_id}/status",
    response_model=VendorOut,
    dependencies=[Depends(require_operations)],
)
def set_vendor_status(
    vendor_id: uuid.UUID,
    body: VendorStatusUpdate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Deactivate (archive) or reactivate a vendor.

    An archived vendor drops out of the default `GET /vendors` list and out
    of new-purchase-order vendor pickers, but `GET /vendors/{vendor_id}`
    keeps resolving it unconditionally so historical purchase orders still
    render correctly.
    """
    with http_errors():
        return service.set_active(db, company_id, vendor_id, body.is_active)
