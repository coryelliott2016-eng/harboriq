"""Stripe Checkout for HarborIQ customer invoices — thin, mockable wrapper.

This module is intentionally the ONLY place that imports the `stripe` SDK for
invoice payment collection. Tests monkeypatch `create_checkout_session`
directly rather than mocking HTTP, so nothing here makes a real network call
in CI.

Scope note (see README "Payment architecture"): this phase charges through
the platform's own Stripe account. Full Stripe Connect — a connected account
per tenant plus `application_fee_amount` so HarborIQ takes a cut of each
transaction while the shop is the merchant of record — is deferred. Wiring
Connect later only changes how this function builds the session (an
`stripe_account` header / `on_behalf_of` + `application_fee_amount`); nothing
about the invoice lifecycle in `app.services.invoices` needs to change.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.config import settings


def create_checkout_session(
    company_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount_total: Decimal,
    currency: str = "USD",
    customer_email: str | None = None,
) -> dict | None:
    """Create a Stripe Checkout Session for paying one HarborIQ invoice.

    Returns `{"id": ..., "url": ...}`, or `None` if Stripe is not configured
    (`settings.stripe_api_key` empty) or the API call fails for any reason.
    Sending/re-fetching an invoice must keep working even with no Stripe
    account wired up — a missing/broken payment processor is a degraded
    experience, not a reason to block billing.
    """
    if not settings.stripe_api_key:
        return None

    try:
        import stripe

        stripe.api_key = settings.stripe_api_key
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {"name": f"Invoice {invoice_id}"},
                        # Stripe wants integer minor units; amount_total is a
                        # NUMERIC(12,2) Decimal dollars value.
                        "unit_amount": int((amount_total * 100).to_integral_value()),
                    },
                    "quantity": 1,
                }
            ],
            customer_email=customer_email or None,
            metadata={
                "company_id": str(company_id),
                "invoice_id": str(invoice_id),
                "kind": "invoice_payment",
            },
            success_url=f"{_base_url()}/pay/{invoice_id}?checkout=success",
            cancel_url=f"{_base_url()}/pay/{invoice_id}?checkout=canceled",
        )
        return {"id": session.id, "url": session.url}
    except Exception:  # noqa: BLE001 — any Stripe/network failure degrades gracefully
        return None


def _base_url() -> str:
    """Placeholder public base URL for Checkout redirects.

    The customer portal frontend does not exist yet (README, "What's
    intentionally NOT here yet"); the redirect targets are cosmetic — Stripe
    requires syntactically valid URLs, and the invoice's actual state change
    happens via webhook, not via whatever page the browser lands on.
    """
    return "https://app.harboriq.example"
