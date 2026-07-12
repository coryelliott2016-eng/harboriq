from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_service_db
from app.schemas.webhooks import StripeEvent
from app.services.stripe_webhooks import handle_stripe_webhook

router = APIRouter()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_service_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    """Idempotent Stripe webhook endpoint.

    NOTE: in production, verify the Stripe-Signature against the raw body using
    stripe.Webhook.constructEvent(payload, sig, webhook_secret). This scaffold
    parses the JSON body directly for testability; the service layer enforces
    idempotency and tenant resolution regardless of signature verification.
    """
    raw = await request.body()
    import json

    try:
        event = StripeEvent.model_validate(json.loads(raw))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}")

    # TODO: verify signature here (requires raw body + STRIPE_WEBHOOK_SECRET).

    status = handle_stripe_webhook(db, event.id, event.type, event.model_dump())
    return Response(status_code=status)
