"""Customer-facing portal routes (Phase 9) — token-gated, NOT staff-gated.

Every route here resolves its `public_token` path segment the same way
`app/api/v1/routes/public.py` already does: a service-role global lookup
(`resolve_portal_token`), then everything else runs scoped to that
`(company_id, customer_id)` pair. A wrong/expired/revoked token is always a
404, never a 401 — consistent with the rest of the public-token surface, so
a guess never confirms a token existed.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.db.session import get_service_db
from app.schemas.messages import MessageCreate, MessageOut
from app.schemas.portal import (
    PortalApproveTokenOut,
    PortalEstimateOut,
    PortalInvoiceOut,
    PortalJobOut,
    PortalMeOut,
    PortalVesselOut,
)
from app.services import messages as messages_service
from app.services import portal as portal_service
from app.services.crud import NotFound
from app.services.public_tokens import InvalidToken

router = APIRouter(prefix="/portal", tags=["portal"])


def _resolve(public_token: str, db=Depends(get_service_db)):
    """Shared dependency: resolve the token or 404. Yields `(db, company_id,
    customer_id)` so every route below gets a ready-to-use, already-scoped
    triple without repeating the try/except."""
    try:
        resolved = portal_service.resolve_portal_token(db, public_token)
    except InvalidToken:
        raise HTTPException(status_code=404)
    return db, resolved["company_id"], resolved["customer_id"]


@router.get("/{public_token}/me", response_model=PortalMeOut)
def get_me(ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    try:
        data = portal_service.get_profile(db, company_id, customer_id)
    except NotFound:
        raise HTTPException(status_code=404)
    out = PortalMeOut.model_validate(data["customer"])
    out.vessels = [PortalVesselOut.model_validate(v) for v in data["vessels"]]
    return out


@router.get("/{public_token}/jobs", response_model=list[PortalJobOut])
def get_jobs(ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    return portal_service.list_jobs(db, company_id, customer_id)


@router.get("/{public_token}/invoices", response_model=list[PortalInvoiceOut])
def get_invoices(ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    return portal_service.list_invoices(db, company_id, customer_id)


@router.get("/{public_token}/invoices/{invoice_id}/pay-url")
def get_invoice_pay_url(invoice_id: uuid.UUID, ctx: tuple = Depends(_resolve)):
    """Hands back the SAME `invoice_pay` checkout flow already used by
    `GET /public/invoice/{token}` -- the portal does not reimplement
    payment, it links to it. 404s if the invoice is not this customer's."""
    db, company_id, customer_id = ctx
    from app.services import invoices as invoices_service

    invoices = portal_service.list_invoices(db, company_id, customer_id)
    if not any(inv.id == invoice_id for inv in invoices):
        raise HTTPException(status_code=404)
    try:
        checkout_url = invoices_service.get_or_create_checkout_url(
            db, company_id, invoice_id
        )
    except NotFound:
        raise HTTPException(status_code=404)
    return {"checkout_url": checkout_url}


@router.get("/{public_token}/estimates", response_model=list[PortalEstimateOut])
def get_estimates(ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    return portal_service.list_estimates(db, company_id, customer_id)


@router.post(
    "/{public_token}/estimates/{estimate_id}/approve-token",
    response_model=PortalApproveTokenOut,
)
def get_estimate_approve_token(estimate_id: uuid.UUID, ctx: tuple = Depends(_resolve)):
    """Issues a fresh, single-purpose `estimate_approve` token so the portal
    can hand the browser the path to the SAME existing public approval
    endpoint (`POST /public/estimate/{token}/approve`) rather than the
    portal duplicating approval logic itself."""
    db, company_id, customer_id = ctx
    raw_token = portal_service.get_estimate_approve_token(
        db, company_id, customer_id, estimate_id
    )
    if raw_token is None:
        raise HTTPException(status_code=404)
    return PortalApproveTokenOut(approve_path=f"/api/v1/public/estimate/{raw_token}/approve")


@router.get("/{public_token}/messages", response_model=list[MessageOut])
def get_messages(job_id: uuid.UUID | None = None, ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    return messages_service.list_for_customer(db, company_id, customer_id, job_id=job_id)


@router.post("/{public_token}/messages", response_model=MessageOut)
def post_message(body: MessageCreate, ctx: tuple = Depends(_resolve)):
    db, company_id, customer_id = ctx
    try:
        return messages_service.send_from_customer(
            db, company_id, customer_id, body.body, job_id=body.job_id
        )
    except NotFound:
        raise HTTPException(status_code=404)
