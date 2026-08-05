"""Inbound SMS webhook (Phase 11) — public, unauthenticated, Twilio-shaped.

Register this URL (`{APP_BASE_URL}/api/v1/webhooks/sms/inbound`) as the
"A message comes in" webhook on the shop's Twilio phone number once real
Twilio credentials are configured. See `app/services/sms_webhooks.py` for
company/customer resolution and `app.services.sms` for the outbound side.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.core.config import settings
from app.services.sms_webhooks import receive_inbound_sms, verify_twilio_signature

logger = logging.getLogger("harboriq.sms")

router = APIRouter()


@router.post("/webhooks/sms/inbound")
async def inbound_sms(
    request: Request,
    db: Session = Depends(get_service_db),
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
):
    """Twilio posts `From`/`Body` (plus other fields we ignore) as standard
    form data on every inbound SMS/MMS.

    Signature verification is enforced only once `TWILIO_AUTH_TOKEN` is
    configured — with no Twilio account connected in this workspace, hard-
    failing every request here would make the endpoint untestable and
    would not protect anything. That is the same shape of trade-off
    `stripe_webhook` already documents for `Stripe-Signature`.
    """
    form = await request.form()
    from_number = str(form.get("From", ""))
    body = str(form.get("Body", ""))

    if not settings.twilio_auth_token:
        logger.warning(
            "TWILIO_AUTH_TOKEN not configured — accepting inbound SMS "
            "without signature verification"
        )
    else:
        url = str(request.url)
        params = {k: str(v) for k, v in form.items()}
        if not verify_twilio_signature(url, params, x_twilio_signature):
            return Response(status_code=403, content="invalid signature")

    receive_inbound_sms(db, from_number=from_number, body=body)

    # Twilio expects a 200 with an (optionally empty) TwiML response; an
    # empty <Response/> means "no auto-reply", which is correct here since
    # staff reply from the Messages inbox, not via an inline TwiML message.
    return Response(
        status_code=200,
        media_type="text/xml",
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
    )
