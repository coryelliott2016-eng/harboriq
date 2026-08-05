import json
import logging

import stripe
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.core.config import settings
from app.schemas.webhooks import StripeEvent
from app.services.outbox_dispatch import dispatch_outbox_soon
from app.services.stripe_webhooks import handle_stripe_webhook

logger = logging.getLogger("harboriq.stripe_webhooks")

router = APIRouter()


def _verify_and_parse(raw: bytes, stripe_signature: str | None) -> dict:
    """Verify `Stripe-Signature` against the raw body and return the parsed event.

    Security-critical (Harbor IQ Security Core Prompt v1.0, "API Security" /
    "Zero Trust"): this endpoint drives real money -- marking invoices paid and
    activating subscriptions -- so a forged, unsigned payload must never reach
    `handle_stripe_webhook`. `stripe.Webhook.construct_event` verifies the
    HMAC-SHA256 signature in `Stripe-Signature` against the *raw* request
    body (never the re-serialized/parsed JSON, which would not match Stripe's
    signed bytes) and rejects expired/replayed timestamps per Stripe's own
    tolerance window.

    Fail-closed by APP_ENV, mirroring `Settings._require_strong_jwt_secret_
    outside_development`:
      - `STRIPE_WEBHOOK_SECRET` configured -> always verify, reject on failure.
      - Unconfigured in production -> hard-reject every event (503): accepting
        unverified financial events in production is strictly worse than
        temporary unavailability.
      - Unconfigured in development -> parse without verification (logged),
        so local/dev testing works without real Stripe webhook credentials.
    """
    if settings.stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(
                raw, stripe_signature, settings.stripe_webhook_secret
            )
        except (stripe.error.SignatureVerificationError, ValueError) as exc:
            logger.warning("rejected stripe webhook: invalid signature (%s)", exc)
            raise HTTPException(status_code=400, detail="invalid signature") from exc
        return event.to_dict()

    if settings.app_env != "development":
        logger.error(
            "STRIPE_WEBHOOK_SECRET is not configured in APP_ENV=%r -- "
            "refusing to process any webhook event unverified",
            settings.app_env,
        )
        raise HTTPException(
            status_code=503,
            detail="webhook signature verification is not configured",
        )

    logger.warning(
        "STRIPE_WEBHOOK_SECRET not set -- accepting webhook without signature "
        "verification (development only)"
    )
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_service_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    """Idempotent, signature-verified Stripe webhook endpoint.

    Signature verification happens first, against the raw body, before any
    parsing or side effect (see `_verify_and_parse`). Only a payload Stripe
    itself signed can reach `handle_stripe_webhook`.
    """
    raw = await request.body()
    verified = _verify_and_parse(raw, stripe_signature)

    try:
        event = StripeEvent.model_validate(verified)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}")

    status = handle_stripe_webhook(db, event.id, event.type, event.model_dump())
    dispatch_outbox_soon(background_tasks)
    return Response(status_code=status)
