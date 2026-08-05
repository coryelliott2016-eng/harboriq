"""Stripe webhook signature verification (Security Core Prompt v1.0, C-1 fix).

A forged/unsigned payload must never reach `handle_stripe_webhook`. These
tests exercise the HTTP route directly (unlike
`test_stripe_webhook_idempotency.py` / `test_stripe_invoice_webhook.py`,
which call the service function and are unaffected by signature
verification), using monkeypatched settings so no real Stripe credentials
are required.
"""
from __future__ import annotations

import json

import stripe

from app.core.config import settings


def _sign(payload: bytes, secret: str) -> str:
    """Build a real Stripe-Signature header value the SDK will accept."""
    import time

    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = stripe.WebhookSignature._compute_signature(signed_payload, secret)
    return f"t={timestamp},v1={signature}"


def _event_body(company_id: str, event_id: str = "evt_sig_test") -> bytes:
    # A subscription-checkout event with no `metadata.kind` (routes to the
    # still-stubbed `_on_subscription_checkout_completed`, which no-ops when
    # no matching subscription row exists) -- these tests only exercise
    # signature verification at the route layer, not the business outcome.
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test",
                    "object": "checkout.session",
                    "metadata": {"company_id": company_id},
                }
            },
        }
    ).encode()


def test_valid_signature_is_accepted(client, monkeypatch, company_a):
    secret = "whsec_test_secret_0123456789"
    monkeypatch.setattr(settings, "stripe_webhook_secret", secret)
    body = _event_body(str(company_a))
    resp = client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": _sign(body, secret)},
    )
    assert resp.status_code == 200


def test_missing_signature_is_rejected(client, monkeypatch, company_a):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret_0123456789")
    resp = client.post("/api/v1/webhooks/stripe", content=_event_body(str(company_a)))
    assert resp.status_code == 400


def test_forged_signature_is_rejected(client, monkeypatch, company_a):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret_0123456789")
    body = _event_body(str(company_a))
    resp = client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert resp.status_code == 400


def test_signature_computed_for_different_secret_is_rejected(client, monkeypatch, company_a):
    """A payload signed with the WRONG secret (e.g. another tenant's/attacker's
    own Stripe test account) must not be accepted."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret_0123456789")
    body = _event_body(str(company_a))
    resp = client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": _sign(body, "whsec_attacker_secret")},
    )
    assert resp.status_code == 400


def test_unconfigured_secret_in_production_hard_rejects(client, monkeypatch, company_a):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(settings, "app_env", "production")
    resp = client.post("/api/v1/webhooks/stripe", content=_event_body(str(company_a)))
    assert resp.status_code == 503


def test_unconfigured_secret_in_development_accepts_unverified(client, monkeypatch, company_a):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(settings, "app_env", "development")
    resp = client.post("/api/v1/webhooks/stripe", content=_event_body(str(company_a)))
    assert resp.status_code == 200
