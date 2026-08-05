"""Slip reservation lifecycle + storage-billing endpoints (Phase 15).

All mutating routes are `require_operations`-gated, same as
`purchase_orders.py` -- booking/confirming/billing a slip is an operations
action.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.invoices import InvoiceDetail, InvoiceLineItemOut
from app.schemas.slip_reservations import (
    GenerateInvoiceFromReservationRequest,
    GenerateStorageChargeRequest,
    SlipAvailabilityOut,
    SlipReservationCreate,
    SlipReservationOut,
    StorageChargeOut,
)
from app.services import invoices as invoices_service
from app.services import slip_reservations as service
from app.services import slips as slips_service

router = APIRouter(prefix="/slip-reservations", tags=["slip-reservations"])


@router.post(
    "",
    response_model=SlipReservationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_reservation(
    body: SlipReservationCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.create(
            db,
            company_id,
            body.slip_id,
            body.customer_id,
            body.start_date,
            body.end_date,
            vessel_id=body.vessel_id,
            notes=body.notes,
        )


@router.get("", response_model=list[SlipReservationOut])
def list_reservations(
    slip_id: uuid.UUID | None = Query(default=None),
    customer_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_reservations(
        db, company_id, slip_id=slip_id, customer_id=customer_id, status=status_filter
    )


@router.get("/availability", response_model=SlipAvailabilityOut)
def check_availability(
    slip_id: uuid.UUID,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Advisory check: does this slip look free for [start_date, end_date]?

    Not a lock -- see `app.services.slips.is_available`'s docstring for why
    the actual double-booking guarantee is the database's EXCLUDE
    constraint, not this endpoint.
    """
    available = slips_service.is_available(db, company_id, slip_id, start_date, end_date)
    return SlipAvailabilityOut(
        slip_id=slip_id, start_date=start_date, end_date=end_date, available=available
    )


@router.get("/{reservation_id}", response_model=SlipReservationOut)
def get_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, reservation_id)


@router.post(
    "/{reservation_id}/confirm",
    response_model=SlipReservationOut,
    dependencies=[Depends(require_operations)],
)
def confirm_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.confirm(db, company_id, reservation_id)


@router.post(
    "/{reservation_id}/check-in",
    response_model=SlipReservationOut,
    dependencies=[Depends(require_operations)],
)
def check_in_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.check_in(db, company_id, reservation_id)


@router.post(
    "/{reservation_id}/check-out",
    response_model=SlipReservationOut,
    dependencies=[Depends(require_operations)],
)
def check_out_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.check_out(db, company_id, reservation_id)


@router.post(
    "/{reservation_id}/cancel",
    response_model=SlipReservationOut,
    dependencies=[Depends(require_operations)],
)
def cancel_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.cancel(db, company_id, reservation_id)


@router.post(
    "/{reservation_id}/generate-storage-charge",
    response_model=StorageChargeOut,
    dependencies=[Depends(require_operations)],
)
def generate_storage_charge(
    reservation_id: uuid.UUID,
    body: GenerateStorageChargeRequest,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Create the `storage`-kind `job_line_items` row billing this
    reservation's stay. Call `POST /slip-reservations/{id}/generate-invoice`
    afterward to freeze it onto an actual invoice."""
    with http_errors():
        return service.generate_storage_charge(
            db,
            company_id,
            reservation_id,
            rate=body.rate,
            quantity=body.quantity,
            description=body.description,
        )


@router.post(
    "/{reservation_id}/generate-invoice",
    response_model=InvoiceDetail,
    dependencies=[Depends(require_operations)],
)
def generate_invoice_from_reservation(
    reservation_id: uuid.UUID,
    body: GenerateInvoiceFromReservationRequest,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Freeze this reservation's uninvoiced storage line(s) onto a new
    invoice -- the exact same mechanism `POST /invoices` uses for job
    labor/part/fee lines, just keyed off the reservation instead."""
    with http_errors():
        result = invoices_service.create_invoice_from_reservation(
            db, company_id, reservation_id, tax_rate=body.tax_rate
        )
    detail = InvoiceDetail.model_validate(result["invoice"])
    detail.line_items = [
        InvoiceLineItemOut.model_validate(item) for item in result["line_items"]
    ]
    return detail
