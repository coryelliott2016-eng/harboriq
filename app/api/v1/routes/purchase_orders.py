"""Purchase order endpoints: draft, list/get, submit, receive, cancel.

All mutating routes are `require_operations`-gated, same as `vessels.py` /
`vendors.py` -- placing and receiving orders is an operations action, not
something a field technician's read-mostly role needs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_current_user, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.purchase_orders import (
    PurchaseOrderCreate,
    PurchaseOrderOut,
    ReceivePurchaseOrderRequest,
)
from app.services import purchase_orders as service
from app.services.auth import AuthenticatedUser

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


@router.post(
    "",
    response_model=PurchaseOrderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_purchase_order(
    body: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a `draft` PO with its line items. Nothing is sent to the
    vendor yet -- see `POST /purchase-orders/{id}/submit`."""
    with http_errors():
        return service.create_draft(
            db,
            company_id,
            user.id,
            body.vendor_id,
            [li.model_dump() for li in body.line_items],
            notes=body.notes,
        )


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_purchase_orders(db, company_id, status=status_filter)


@router.get("/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.get(db, company_id, po_id)


@router.post(
    "/{po_id}/submit",
    response_model=PurchaseOrderOut,
    dependencies=[Depends(require_operations)],
)
def submit_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """The human commitment point: `draft` -> `submitted`."""
    with http_errors():
        return service.submit(db, company_id, po_id)


@router.post(
    "/{po_id}/receive",
    response_model=PurchaseOrderOut,
    dependencies=[Depends(require_operations)],
)
def receive_purchase_order(
    po_id: uuid.UUID,
    body: ReceivePurchaseOrderRequest,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Record actual received quantities (may be partial) and increment
    `quantity_on_hand` through the same guarded writer `POST /inventory/use`
    uses to decrement it."""
    with http_errors():
        return service.receive(
            db, company_id, po_id, [r.model_dump() for r in body.receipts]
        )


@router.post(
    "/{po_id}/cancel",
    response_model=PurchaseOrderOut,
    dependencies=[Depends(require_operations)],
)
def cancel_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        return service.cancel(db, company_id, po_id)
