"""Phase 18 — licensed-processor crypto payment rail coverage."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal

from sqlalchemy import text

from app.core.config import settings
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


class FakeCryptoProvider:
    """No test makes a real Stripe API call."""

    def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
        company_id: uuid.UUID,
        metadata: dict[str, str],
    ) -> dict[str, str]:
        return {
            "provider_reference": f"crypto_session_{uuid.uuid4().hex}",
            "checkout_url_or_address": f"https://crypto.test/pay/{invoice_id}",
        }


def _invoiced_job(client, actor, unit_price: str = "100.00") -> dict:
    customer = make_customer(client, actor)
    job = make_job(client, actor, customer).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={
            "kind": "labor",
            "description": "Crypto payment test work",
            "quantity": "1.00",
            "unit_price": unit_price,
        },
        headers=auth_headers(actor),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    ).json()
    response = client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(actor)
    )
    assert response.status_code == 200, response.text
    return invoice


def _enable_fake_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "crypto_payments_enabled", True)
    monkeypatch.setattr(
        "app.services.crypto_payments.get_crypto_provider", lambda: FakeCryptoProvider()
    )


def _create_intent(client, actor, invoice_id: str, amount: str = "100.00") -> dict:
    response = client.post(
        f"/api/v1/invoices/{invoice_id}/crypto-payment-intent",
        json={"amount": amount, "currency": "usdc"},
        headers=auth_headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _event(intent: dict, company_id: str, invoice_id: str, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"crypto_evt_{uuid.uuid4().hex}",
        "type": "crypto.payment.confirmed",
        "company_id": company_id,
        "invoice_id": invoice_id,
        "provider": intent["payment"]["provider"],
        "provider_reference": intent["payment"]["provider_reference"],
    }


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_feature_flag_off_returns_not_found(client, monkeypatch):
    owner = signup(client)
    monkeypatch.setattr(settings, "crypto_payments_enabled", False)

    response = client.post(
        f"/api/v1/invoices/{uuid.uuid4()}/crypto-payment-intent",
        json={"amount": "10.00", "currency": "usdc"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "crypto payments are not enabled"


def test_valid_hmac_signature_is_accepted(client, monkeypatch):
    _enable_fake_provider(monkeypatch)
    secret = "crypto-webhook-test-secret"
    monkeypatch.setattr(settings, "crypto_webhook_secret", secret)
    owner = signup(client)
    invoice = _invoiced_job(client, owner)
    intent = _create_intent(client, owner, invoice["id"])
    body = json.dumps(_event(intent, owner["user"]["company_id"], invoice["id"])).encode()

    response = client.post(
        "/api/v1/webhooks/crypto",
        content=body,
        headers={"X-Crypto-Signature": _signature(body, secret)},
    )
    assert response.status_code == 200, response.text


def test_invalid_hmac_signature_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "crypto_webhook_secret", "crypto-webhook-test-secret")
    body = json.dumps(
        {
            "id": "crypto_evt_bad_signature",
            "type": "crypto.payment.confirmed",
            "company_id": str(uuid.uuid4()),
            "invoice_id": str(uuid.uuid4()),
            "provider_reference": "fake",
        }
    ).encode()
    response = client.post(
        "/api/v1/webhooks/crypto",
        content=body,
        headers={"X-Crypto-Signature": "deadbeef"},
    )
    assert response.status_code == 400


def test_unconfigured_secret_in_non_development_hard_rejects(client, monkeypatch):
    monkeypatch.setattr(settings, "crypto_webhook_secret", "")
    monkeypatch.setattr(settings, "app_env", "production")
    response = client.post("/api/v1/webhooks/crypto", content=b"{}")
    assert response.status_code == 503


def test_unconfigured_secret_in_development_accepts_with_warning(
    client, monkeypatch, caplog
):
    _enable_fake_provider(monkeypatch)
    monkeypatch.setattr(settings, "crypto_webhook_secret", "")
    monkeypatch.setattr(settings, "app_env", "development")
    owner = signup(client)
    invoice = _invoiced_job(client, owner)
    intent = _create_intent(client, owner, invoice["id"])

    with caplog.at_level(logging.WARNING, logger="harboriq.crypto_payments"):
        response = client.post(
            "/api/v1/webhooks/crypto",
            content=json.dumps(_event(intent, owner["user"]["company_id"], invoice["id"])),
        )
    assert response.status_code == 200, response.text
    assert "CRYPTO_WEBHOOK_SECRET not set" in caplog.text


def test_confirmed_webhook_partially_pays_invoice_and_replay_is_idempotent(
    client, monkeypatch, service_db
):
    _enable_fake_provider(monkeypatch)
    secret = "crypto-webhook-test-secret"
    monkeypatch.setattr(settings, "crypto_webhook_secret", secret)
    owner = signup(client)
    invoice = _invoiced_job(client, owner)
    intent = _create_intent(client, owner, invoice["id"], amount="40.00")
    event = _event(intent, owner["user"]["company_id"], invoice["id"])
    body = json.dumps(event).encode()
    headers = {"X-Crypto-Signature": _signature(body, secret)}

    first = client.post("/api/v1/webhooks/crypto", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/crypto", content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    invoice_row = service_db.execute(
        text("SELECT status, amount_paid, balance_due FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert invoice_row.status == "partial"
    assert str(invoice_row.amount_paid) == "40.00"
    assert str(invoice_row.balance_due) == "60.00"

    payment_row = service_db.execute(
        text(
            """
            SELECT status, confirmed_at
              FROM crypto_payments
             WHERE id = :id
            """
        ),
        {"id": intent["payment"]["id"]},
    ).first()
    assert payment_row.status == "confirmed"
    assert payment_row.confirmed_at is not None

    processed_events = service_db.execute(
        text("SELECT count(*) FROM crypto_processed_events WHERE event_id = :id"),
        {"id": event["id"]},
    ).scalar_one()
    payments = service_db.execute(
        text("SELECT count(*) FROM payments WHERE invoice_id = :id"),
        {"id": invoice["id"]},
    ).scalar_one()
    invoice_paid_events = service_db.execute(
        text(
            """
            SELECT count(*)
              FROM outbox_events
             WHERE event_type = 'invoice.paid'
               AND payload->>'crypto_payment_id' = :payment_id
            """
        ),
        {"payment_id": intent["payment"]["id"]},
    ).scalar_one()
    assert processed_events == 1
    assert payments == 1
    assert invoice_paid_events == 1


def test_failed_webhook_marks_crypto_payment_without_touching_invoice(
    client, monkeypatch, service_db
):
    _enable_fake_provider(monkeypatch)
    secret = "crypto-webhook-test-secret"
    monkeypatch.setattr(settings, "crypto_webhook_secret", secret)
    owner = signup(client)
    invoice = _invoiced_job(client, owner)
    intent = _create_intent(client, owner, invoice["id"], amount="40.00")
    event = _event(intent, owner["user"]["company_id"], invoice["id"])
    event["type"] = "crypto.payment.failed"
    body = json.dumps(event).encode()

    response = client.post(
        "/api/v1/webhooks/crypto",
        content=body,
        headers={"X-Crypto-Signature": _signature(body, secret)},
    )
    assert response.status_code == 200, response.text

    invoice_row = service_db.execute(
        text("SELECT status, amount_paid FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    payment_row = service_db.execute(
        text("SELECT status FROM crypto_payments WHERE id = :id"),
        {"id": intent["payment"]["id"]},
    ).first()
    assert invoice_row.status == "sent"
    assert str(invoice_row.amount_paid) == "0.00"
    assert payment_row.status == "failed"


def test_crypto_payment_is_not_visible_to_another_tenant(client, monkeypatch):
    _enable_fake_provider(monkeypatch)
    owner_a = signup(client, company_name="Crypto Tenant A")
    invoice = _invoiced_job(client, owner_a)
    intent = _create_intent(client, owner_a, invoice["id"])
    owner_b = signup(client, company_name="Crypto Tenant B")

    response = client.get(
        f"/api/v1/crypto-payments/{intent['payment']['id']}",
        headers=auth_headers(owner_b),
    )
    assert response.status_code == 404
