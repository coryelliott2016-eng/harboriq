"""Licensed-processor stablecoin invoice payments (Phase 18).

This module deliberately owns no wallet, private key, or on-chain custody
logic.  It creates a checkout with a licensed processor and records the
processor's signed webhook result using the same transaction/idempotency
discipline as the existing Stripe card-payment rail.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import invoices, outbox
from app.services.crud import Conflict, NotFound

DEFAULT_PROVIDER = "stripe_stablecoin"
CONFIRMED_EVENT_TYPES = frozenset(
    {"crypto.payment.confirmed", "crypto_payment.confirmed", "confirmed"}
)
FAILED_EVENT_TYPES = frozenset({"crypto.payment.failed", "crypto_payment.failed", "failed"})
EXPIRED_EVENT_TYPES = frozenset({"crypto.payment.expired", "crypto_payment.expired", "expired"})


class CryptoPaymentProvider(Protocol):
    """Minimal provider seam; tests replace this rather than making HTTP calls."""

    def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
        company_id: uuid.UUID,
        metadata: dict[str, str],
    ) -> dict[str, str]: ...


class CryptoPaymentsNotConfigured(RuntimeError):
    """Raised if a disabled/unconfigured crypto rail is called internally."""


class NullCryptoProvider:
    """Safe default: no hidden fallback to an unconfigured processor."""

    def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
        company_id: uuid.UUID,
        metadata: dict[str, str],
    ) -> dict[str, str]:
        raise CryptoPaymentsNotConfigured("crypto payments not configured")


class StripeStablecoinProvider:
    """Stripe Checkout implementation for accounts enabled for crypto payments.

    Stripe's Checkout `crypto` payment method is presently priced in USD; the
    customer settles through Stripe's supported stablecoin option.  The
    requested asset is nevertheless persisted as `currency` (normally USDC)
    for operations/audit.  Going live requires Stripe to enable
    stablecoin/crypto payments for the connected Stripe account.
    """

    def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
        company_id: uuid.UUID,
        metadata: dict[str, str],
    ) -> dict[str, str]:
        import stripe

        stripe.api_key = settings.stripe_api_key
        # `stripe_account` is a request option, never provider-visible
        # Checkout metadata.  The service supplies it only when the tenant
        # completed the existing Stripe Connect onboarding.
        request_options = (
            {"stripe_account": metadata["_stripe_account"]}
            if metadata.get("_stripe_account")
            else {}
        )
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["crypto"],
            line_items=[
                {
                    "price_data": {
                        # Stripe Checkout's crypto payment method currently
                        # accepts USD pricing; Stripe handles the USDC leg.
                        "currency": "usd",
                        "product_data": {"name": f"Invoice {invoice_id} (stablecoin)"},
                        "unit_amount": int(
                            (amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
                        ),
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                **{key: value for key, value in metadata.items() if not key.startswith("_")},
                "kind": "crypto_invoice_payment",
                "invoice_id": str(invoice_id),
                "company_id": str(company_id),
                "crypto_currency": currency.lower(),
            },
            success_url=(
                f"{settings.app_base_url.rstrip('/')}/pay/"
                f"{invoice_id}?crypto_checkout=success"
            ),
            cancel_url=(
                f"{settings.app_base_url.rstrip('/')}/pay/"
                f"{invoice_id}?crypto_checkout=canceled"
            ),
            **request_options,
        )
        return {"provider_reference": session.id, "checkout_url_or_address": session.url}


def get_crypto_provider() -> CryptoPaymentProvider:
    """Return an active provider only when the explicit integration is ready."""
    if settings.crypto_payments_enabled and settings.stripe_api_key:
        return StripeStablecoinProvider()
    return NullCryptoProvider()


def create_crypto_payment_intent(
    db: Session,
    company_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal,
    currency: str = "usdc",
) -> dict[str, Any]:
    """Create a pending provider checkout for a sent or partially paid invoice."""
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise Conflict("crypto payment amount must be greater than zero")

    with tenant_context(db, company_id):
        invoice = db.execute(
            text(
                """
                SELECT id, status, balance_due
                  FROM invoices
                 WHERE id = :invoice_id
                 FOR UPDATE
                """
            ),
            {"invoice_id": invoice_id},
        ).first()
        if invoice is None:
            db.rollback()
            raise NotFound(f"invoice {invoice_id} not found")
        if invoice.status not in {"sent", "partial"}:
            db.rollback()
            raise Conflict("invoice must be sent or partial before requesting a crypto payment")
        if amount > invoice.balance_due:
            db.rollback()
            raise Conflict("crypto payment amount cannot exceed the invoice balance due")

        company = db.execute(
            text("SELECT stripe_connect_account_id FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        ).first()
        payment = db.execute(
            text(
                """
                INSERT INTO crypto_payments
                    (company_id, invoice_id, provider, currency, amount_requested,
                     status, raw_metadata)
                VALUES
                    (:company_id, :invoice_id, :provider, :currency, :amount,
                     'pending', CAST(:metadata AS jsonb))
                RETURNING *
                """
            ),
            {
                "company_id": company_id,
                "invoice_id": invoice_id,
                "provider": DEFAULT_PROVIDER,
                "currency": currency.lower(),
                "amount": amount,
                "metadata": '{"kind":"crypto_invoice_payment"}',
            },
        ).first()

        try:
            provider_metadata = {
                "kind": "crypto_invoice_payment",
                "invoice_id": str(invoice_id),
                "company_id": str(company_id),
            }
            if company and company.stripe_connect_account_id:
                provider_metadata["_stripe_account"] = company.stripe_connect_account_id
            provider_response = get_crypto_provider().create_payment(
                amount=amount,
                currency=currency.lower(),
                invoice_id=invoice_id,
                company_id=company_id,
                metadata=provider_metadata,
            )
        except Exception:
            db.rollback()
            raise

        provider_reference = provider_response.get("provider_reference")
        checkout_url_or_address = provider_response.get("checkout_url_or_address")
        if not provider_reference or not checkout_url_or_address:
            db.rollback()
            raise RuntimeError("crypto payment provider returned an incomplete payment intent")

        payment = db.execute(
            text(
                """
                UPDATE crypto_payments
                   SET provider_reference = :provider_reference,
                       raw_metadata = raw_metadata || CAST(:metadata AS jsonb)
                 WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": payment.id,
                "provider_reference": provider_reference,
                "metadata": (
                    '{"checkout_url_or_address":'
                    + _json_string(checkout_url_or_address)
                    + "}"
                ),
            },
        ).first()
        # Stamp the Checkout Session id onto the invoice immediately so the
        # real Stripe webhook path (`checkout.session.completed` with
        # kind=crypto_invoice_payment) can resolve the invoice the same way
        # card Checkout does — without requiring a second custom webhook.
        db.execute(
            text(
                """
                UPDATE invoices
                   SET stripe_checkout_session_id = :provider_reference
                 WHERE id = :invoice_id
                """
            ),
            {
                "provider_reference": provider_reference,
                "invoice_id": invoice_id,
            },
        )
        db.commit()

    return {"payment": payment, "checkout_url_or_address": checkout_url_or_address}


def confirm_crypto_payment(
    db: Session,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    company_id: uuid.UUID,
) -> int:
    """Apply a signed provider event exactly once and return HTTP 200.

    The caller is the service-role webhook route.  It resolves `company_id`
    directly from the verified payload, then enters tenant context before
    touching a tenant row.  The dedup insert and every side effect share one
    transaction so an event replay cannot double-apply a payment.
    """
    provider = str(payload.get("provider") or DEFAULT_PROVIDER)
    provider_reference = str(
        payload.get("provider_reference") or payload.get("resource_id") or ""
    )
    if not provider_reference:
        raise ValueError("crypto webhook payload is missing provider_reference")

    with tenant_context(db, company_id):
        inserted = db.execute(
            text(
                """
                INSERT INTO crypto_processed_events
                    (event_id, provider, event_type, company_id, resource_id,
                     http_status, outcome)
                VALUES
                    (:event_id, :provider, :event_type, :company_id,
                     :resource_id, 200, 'applied')
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """
            ),
            {
                "event_id": event_id,
                "provider": provider,
                "event_type": event_type,
                "company_id": company_id,
                "resource_id": provider_reference,
            },
        )
        if inserted.first() is None:
            return 200

        payment = db.execute(
            text(
                """
                SELECT *
                  FROM crypto_payments
                 WHERE provider = :provider
                   AND provider_reference = :provider_reference
                 FOR UPDATE
                """
            ),
            {"provider": provider, "provider_reference": provider_reference},
        ).first()
        if payment is None:
            db.rollback()
            raise NotFound("crypto payment not found for provider reference")
        if str(payment.invoice_id) != str(payload.get("invoice_id")):
            db.rollback()
            raise ValueError("crypto webhook invoice_id does not match the payment")

        if event_type in CONFIRMED_EVENT_TYPES:
            if payment.status == "pending":
                payment = db.execute(
                    text(
                        """
                        UPDATE crypto_payments
                           SET status = 'confirmed', confirmed_at = now(),
                               raw_metadata = COALESCE(raw_metadata, '{}'::jsonb)
                                   || CAST(:payload AS jsonb)
                         WHERE id = :id
                        RETURNING *
                        """
                    ),
                    {"id": payment.id, "payload": _json_payload(payload)},
                ).first()
                # The established, processor-agnostic application path
                # resolves an invoice through a payment identifier.  The
                # current provider reference is a Stripe Checkout Session id,
                # so stamping it on that existing audit column lets us reuse
                # the exact row-locked money/state-machine implementation
                # without treating a Checkout Session as a PaymentIntent.
                db.execute(
                    text(
                        """
                        UPDATE invoices
                           SET stripe_checkout_session_id = :provider_reference
                         WHERE id = :invoice_id
                        """
                    ),
                    {
                        "provider_reference": provider_reference,
                        "invoice_id": payment.invoice_id,
                    },
                )
                invoices.mark_paid_from_webhook(
                    db,
                    company_id,
                    stripe_checkout_session_id=provider_reference,
                    amount_paid_cents=int(
                        (payment.amount_requested * Decimal("100")).to_integral_value(
                            rounding=ROUND_HALF_UP
                        )
                    ),
                )
                outbox.enqueue(
                    db,
                    company_id,
                    "invoice.paid",
                    {
                        "invoice_id": str(payment.invoice_id),
                        "crypto_payment_id": str(payment.id),
                        "provider": provider,
                    },
                )
        elif event_type in FAILED_EVENT_TYPES | EXPIRED_EVENT_TYPES:
            status = "failed" if event_type in FAILED_EVENT_TYPES else "expired"
            payment = db.execute(
                text(
                    """
                    UPDATE crypto_payments
                       SET status = CAST(:status AS crypto_payment_status),
                           raw_metadata = COALESCE(raw_metadata, '{}'::jsonb)
                               || CAST(:payload AS jsonb)
                     WHERE id = :id
                    RETURNING *
                    """
                ),
                {"id": payment.id, "status": status, "payload": _json_payload(payload)},
            ).first()
        # Unknown events are recorded for audit/deduplication but intentionally
        # do not mutate either payment or invoice.

        db.commit()
        return 200


def _json_string(value: str) -> str:
    """Return a JSON string without adding a module dependency at call sites."""
    import json

    return json.dumps(value)


def _json_payload(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, default=str)
