"""Stripe Checkout + Connect for HarborIQ customer invoices — thin, mockable
wrapper.

This module is intentionally the ONLY place that imports the `stripe` SDK for
invoice payment collection. Tests monkeypatch these functions directly rather
than mocking HTTP, so nothing here makes a real network call in CI.

Scope note (see README "Payment architecture"): Phase 8 adds Stripe Connect
Standard accounts using the **direct charge** pattern — once a tenant
onboards, `create_checkout_session` passes `stripe_account=<connect id>` so
the Checkout Session (and therefore the underlying charge/PaymentIntent) is
created directly on the *connected* account. The tenant is the merchant of
record, Stripe settles straight to them, and HarborIQ takes no cut of the
transaction. Destination charges / `application_fee_amount` (HarborIQ taking
a percentage on-behalf-of the platform account while still charging on the
connected account) is a deliberately separate, larger design decision
(revenue model, fee schedule, tax implications) and is out of scope for this
phase — see README "What's intentionally NOT here yet".

Tenants who have not completed Connect onboarding keep working exactly as
before: `create_checkout_session` falls back to creating the session on
HarborIQ's own platform account when `stripe_account` is `None`.
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
    stripe_account: str | None = None,
) -> dict | None:
    """Create a Stripe Checkout Session for paying one HarborIQ invoice.

    Returns `{"id": ..., "url": ...}`, or `None` if Stripe is not configured
    (`settings.stripe_api_key` empty) or the API call fails for any reason.
    Sending/re-fetching an invoice must keep working even with no Stripe
    account wired up — a missing/broken payment processor is a degraded
    experience, not a reason to block billing.

    `stripe_account`: when the tenant has completed Stripe Connect
    onboarding (`companies.stripe_connect_account_id` is set), callers pass
    that id here so the session — and the resulting charge — is created
    directly on the connected account (direct charge pattern) rather than on
    HarborIQ's platform account. `None` preserves the pre-Connect,
    single-platform-account behavior.
    """
    if not settings.stripe_api_key:
        return None

    try:
        import stripe

        stripe.api_key = settings.stripe_api_key
        request_options = {"stripe_account": stripe_account} if stripe_account else {}
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
            **request_options,
        )
        return {"id": session.id, "url": session.url}
    except Exception:  # noqa: BLE001 — any Stripe/network failure degrades gracefully
        return None


def create_connect_account_and_onboarding_link(
    company_id: uuid.UUID, existing_account_id: str | None, return_url: str, refresh_url: str
) -> dict | None:
    """Create (or reuse) a Stripe Connect Standard account and an onboarding
    AccountLink for it.

    Returns `{"account_id": ..., "url": ...}`, or `None` on any failure/
    missing API key — same graceful-degradation convention as
    `create_checkout_session`. `existing_account_id`: if the tenant already
    has a Connect account id on file (e.g. onboarding was started but never
    finished), reuse it and just issue a fresh AccountLink rather than
    creating a duplicate account.
    """
    if not settings.stripe_api_key:
        return None

    try:
        import stripe

        stripe.api_key = settings.stripe_api_key

        account_id = existing_account_id
        if not account_id:
            account = stripe.Account.create(
                type="standard",
                metadata={"company_id": str(company_id)},
            )
            account_id = account.id

        link = stripe.AccountLink.create(
            account=account_id,
            type="account_onboarding",
            return_url=return_url,
            refresh_url=refresh_url,
        )
        return {"account_id": account_id, "url": link.url}
    except Exception:  # noqa: BLE001 — degrade gracefully, same as checkout
        return None


def get_connect_account_status(account_id: str) -> dict | None:
    """Fetch `charges_enabled` / `details_submitted` for a Connect account.

    Returns `None` if Stripe is not configured or the lookup fails.
    """
    if not settings.stripe_api_key:
        return None

    try:
        import stripe

        stripe.api_key = settings.stripe_api_key
        account = stripe.Account.retrieve(account_id)
        return {
            "charges_enabled": bool(account.charges_enabled),
            "details_submitted": bool(account.details_submitted),
        }
    except Exception:  # noqa: BLE001
        return None


def create_refund(
    *,
    payment_intent_id: str | None,
    charge_id: str | None,
    amount: Decimal | None,
    reason: str | None,
    stripe_account: str | None = None,
) -> dict | None:
    """Issue a Stripe refund against a PaymentIntent or charge.

    Returns `{"id": ...}` on success, `None` on any failure/missing
    configuration — callers treat `None` the way `void_invoice`/checkout
    already do: surface a clean error rather than half-apply state.
    `amount`: dollars; `None` means a full refund. `stripe_account`: pass the
    tenant's Connect account id when the original charge was a direct charge
    on that account (mirrors `create_checkout_session`'s fallback rule).
    """
    if not settings.stripe_api_key:
        return None
    if not payment_intent_id and not charge_id:
        return None

    try:
        import stripe

        stripe.api_key = settings.stripe_api_key
        request_options = {"stripe_account": stripe_account} if stripe_account else {}
        kwargs: dict = {}
        if payment_intent_id:
            kwargs["payment_intent"] = payment_intent_id
        elif charge_id:
            kwargs["charge"] = charge_id
        if amount is not None:
            kwargs["amount"] = int((amount * 100).to_integral_value())
        if reason:
            # Stripe only accepts a small enum for `reason`; free-text goes in
            # metadata instead of forcing callers to map to it.
            kwargs["metadata"] = {"reason": reason}

        refund = stripe.Refund.create(**kwargs, **request_options)
        return {"id": refund.id}
    except Exception:  # noqa: BLE001 — any Stripe/network failure degrades gracefully
        return None


def _base_url() -> str:
    """Placeholder public base URL for Checkout/Connect redirects.

    The customer portal frontend does not exist yet (README, "What's
    intentionally NOT here yet"); the redirect targets are cosmetic — Stripe
    requires syntactically valid URLs, and the invoice's actual state change
    happens via webhook, not via whatever page the browser lands on.
    """
    return "https://app.harboriq.example"
