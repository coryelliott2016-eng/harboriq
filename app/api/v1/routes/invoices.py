"""Invoice endpoints — building, sending and voiding a shop's customer bills.

Every endpoint here is gated behind `require_operations` (owner/admin/office).
Per the `UserRole` docstring, "office" explicitly owns "customers, estimates,
invoices" — technicians never touch billing, unlike jobs where an assigned
technician has narrow self-service access (`authorize_job_action`).

Status never moves through a generic PATCH: `send`/`void` are explicit
actions that delegate to `InvoiceSM` in the service layer, so an illegal move
is a 409 rather than a silently corrupt invoice.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_current_user, get_db, require_operations
from app.api.errors import http_errors
from app.schemas.invoices import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceLineItemOut,
    InvoiceListItem,
    InvoiceSendResponse,
    RefundRequest,
    RefundResponse,
    VoidInvoiceResponse,
)
from app.services import invoices as service
from app.services.auth import AuthenticatedUser
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(
    prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_operations)]
)


@router.post("", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Invoice every currently-uninvoiced line on `job_id`.

    409 if the job has nothing left to invoice (either it never had billable
    lines, or a previous invoice already claimed all of them).
    """
    with http_errors():
        result = service.create_invoice(db, company_id, body.job_id, body.tax_rate)
    detail = InvoiceDetail.model_validate(result["invoice"])
    detail.line_items = [
        InvoiceLineItemOut.model_validate(item) for item in result["line_items"]
    ]
    return detail


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    invoice_status: str | None = Query(default=None, alias="status"),
    customer_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    return service.list_invoices(
        db,
        company_id,
        status=invoice_status,
        customer_id=customer_id,
        job_id=job_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    with http_errors():
        invoice = service.get(db, company_id, invoice_id)
        items = service.list_invoice_line_items(db, company_id, invoice_id)
    detail = InvoiceDetail.model_validate(invoice)
    detail.line_items = [InvoiceLineItemOut.model_validate(item) for item in items]
    return detail


@router.post("/{invoice_id}/send", response_model=InvoiceSendResponse)
def send_invoice(
    invoice_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """`draft -> sent`: stamp `sent_at`, best-effort create a Stripe Checkout
    Session, and issue a public pay link. A Stripe outage does not block
    this — the shop can still hand the customer the pay link."""
    with http_errors():
        result = service.send_invoice(db, company_id, invoice_id)
    dispatch_outbox_soon(background_tasks)
    return InvoiceSendResponse(
        invoice=result["invoice"], pay_token=result["pay_token"], pay_url=result["pay_url"]
    )


@router.post("/{invoice_id}/void", response_model=VoidInvoiceResponse)
def void_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Cancel a `draft`, `sent` or `partial` invoice with nothing collected
    yet. 409 if any payment has landed — use `POST /{invoice_id}/refund`
    instead."""
    with http_errors():
        invoice = service.void_invoice(db, company_id, invoice_id)
    return VoidInvoiceResponse(invoice=invoice)


@router.post("/{invoice_id}/refund", response_model=RefundResponse)
def refund_invoice(
    invoice_id: uuid.UUID,
    body: RefundRequest = RefundRequest(),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Refund all or part of a `paid`/`partial` invoice via Stripe.

    Omitting `amount` refunds the full amount collected and moves the
    invoice to `refunded`; a smaller `amount` moves it to
    `partially_refunded`. 409 on an illegal transition (e.g. nothing paid
    yet, or already fully refunded); 502 if Stripe itself rejects/cannot
    process the refund.
    """
    with http_errors():
        result = service.refund_invoice(
            db,
            company_id,
            invoice_id,
            amount=body.amount,
            reason=body.reason,
            created_by=user.id,
        )
    return RefundResponse(invoice=result["invoice"], refund=result["refund"])
