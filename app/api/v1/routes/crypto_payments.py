"""Operations endpoints and signed webhook for Phase 18 crypto payments."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_company_id,
    get_db,
    get_service_db,
    require_operations,
)
from app.api.errors import http_errors
from app.core.config import settings
from app.schemas.crypto_payments import (
    CryptoPaymentIntentCreate,
    CryptoPaymentIntentResponse,
    CryptoPaymentOut,
)
from app.services.crypto_payments import (
    create_crypto_payment_intent,
    confirm_crypto_payment,
)
from app.services.outbox_dispatch import dispatch_outbox_soon

logger = logging.getLogger("harboriq.crypto_payments")

router = APIRouter()


def _verify_and_parse(raw: bytes, signature: str | None) -> dict:
    """Verify the raw JSON HMAC before parsing or applying a financial event."""
    if settings.crypto_webhook_secret:
        expected = hmac.new(
            settings.crypto_webhook_secret.encode(),
            raw,
            hashlib.sha256,
        ).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            logger.warning("rejected crypto webhook: invalid signature")
            raise HTTPException(status_code=400, detail="invalid signature")
    elif settings.app_env != "development":
        logger.error(
            "CRYPTO_WEBHOOK_SECRET is not configured in APP_ENV=%r -- "
            "refusing to process any webhook event unverified",
            settings.app_env,
        )
        raise HTTPException(
            status_code=503,
            detail="webhook signature verification is not configured",
        )
    else:
        logger.warning(
            "CRYPTO_WEBHOOK_SECRET not set -- accepting webhook without signature "
            "verification (development only)"
        )

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="invalid payload: expected JSON object")
    return parsed


@router.post(
    "/invoices/{invoice_id}/crypto-payment-intent",
    response_model=CryptoPaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operations)],
)
def create_intent(
    invoice_id: uuid.UUID,
    body: CryptoPaymentIntentCreate,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Create a Stripe-hosted stablecoin checkout for a sent/partial invoice."""
    if not settings.crypto_payments_enabled:
        raise HTTPException(status_code=404, detail="crypto payments are not enabled")
    with http_errors():
        result = create_crypto_payment_intent(
            db,
            company_id,
            invoice_id,
            body.amount,
            body.currency,
        )
    return CryptoPaymentIntentResponse(
        payment=CryptoPaymentOut.model_validate(result["payment"]),
        checkout_url_or_address=result["checkout_url_or_address"],
    )


@router.get(
    "/crypto-payments/{payment_id}",
    response_model=CryptoPaymentOut,
    dependencies=[Depends(require_operations)],
)
def get_crypto_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Return one tenant-scoped crypto payment without leaking other tenants."""
    row = db.execute(
        text("SELECT * FROM crypto_payments WHERE id = :id"),
        {"id": payment_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="crypto payment not found")
    return CryptoPaymentOut.model_validate(row)


@router.post("/webhooks/crypto")
async def crypto_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_service_db),
    x_crypto_signature: str | None = Header(default=None, alias="X-Crypto-Signature"),
):
    """Verify and process a provider event carrying direct tenant metadata."""
    raw = await request.body()
    event = _verify_and_parse(raw, x_crypto_signature)
    try:
        event_id = str(event["id"])
        event_type = str(event["type"])
        company_id = uuid.UUID(str(event["company_id"]))
        uuid.UUID(str(event["invoice_id"]))
        if not event.get("provider_reference"):
            raise ValueError("provider_reference is required")
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc

    with http_errors():
        result_status = confirm_crypto_payment(
            db, event_id, event_type, event, company_id
        )
    dispatch_outbox_soon(background_tasks)
    return Response(status_code=result_status)
