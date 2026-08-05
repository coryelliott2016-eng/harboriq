
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.schemas.invoices import InvoiceLineItemOut
from app.schemas.public import (
    ApproveEstimateRequest,
    ApproveEstimateResponse,
    PublicInvoiceOut,
)
from app.services import invoices as invoices_service
from app.services.crud import NotFound
from app.services.public_tokens import (
    InvalidToken,
    approve_estimate_with_token,
    resolve_read_only_token,
)
from app.services.state_machines import IllegalTransition

router = APIRouter()


@router.post(
    "/public/estimate/{public_token}/approve",
    response_model=ApproveEstimateResponse,
)
def approve_estimate(
    public_token: str,
    request: Request,
    body: ApproveEstimateRequest,
    db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Public, token-authenticated estimate approval (electronic-signature).

    Uses the SERVICE db (BYPASSRLS) only for the initial global token lookup;
    the actual approval runs inside tenant_context so RLS applies. The whole
    flow is one transaction — a failed transition does not burn the token.
    """
    client_ip = request.client.host if request.client else "0.0.0.0"  # noqa: S104 -- audit-log fallback value, not a bind address
    try:
        result = approve_estimate_with_token(
            db,
            public_token,
            ip=client_ip,
            user_agent=user_agent or "",
            estimate_pdf_version=body.estimate_pdf_version,
        )
    except InvalidToken:
        # 404 (not 401) to avoid leaking token existence.
        raise HTTPException(status_code=404)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ApproveEstimateResponse(**result)


@router.get(
    "/public/invoice/{public_token}",
    response_model=PublicInvoiceOut,
)
def get_public_invoice(
    public_token: str,
    db: Session = Depends(get_service_db),
):
    """Public, token-authenticated invoice pay page.

    Read-only: does NOT consume a token use, since a customer may reload this
    page many times before completing Stripe checkout. The actual payment
    state change happens via the Stripe webhook
    (`_on_invoice_payment_completed`), never through this endpoint. Lazily
    creates (and persists) a Stripe Checkout Session on first read if the
    invoice does not have one yet and is still payable.
    """
    try:
        resolved = resolve_read_only_token(db, public_token, "invoice_pay", "invoice")
    except InvalidToken:
        # 404 (not 401) to avoid leaking token existence.
        raise HTTPException(status_code=404)

    company_id = resolved["company_id"]
    invoice_id = resolved["resource_id"]

    try:
        invoice = invoices_service.get(db, company_id, invoice_id)
        line_items = invoices_service.list_invoice_line_items(db, company_id, invoice_id)
        checkout_url = invoices_service.get_or_create_checkout_url(db, company_id, invoice_id)
    except NotFound:
        raise HTTPException(status_code=404)

    out = PublicInvoiceOut.model_validate(invoice)
    out.line_items = [InvoiceLineItemOut.model_validate(item) for item in line_items]
    out.checkout_url = checkout_url
    return out
