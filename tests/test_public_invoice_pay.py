"""Public invoice pay page — token resolves the right invoice, read-only.

Mirrors `tests/test_public_tokens.py`'s conventions, but for the read-only
`invoice_pay` token contract: unlike `estimate_approve`, this token must
NEVER be consumed by a read (`uses` stays untouched across repeated loads),
because the actual payment happens via Stripe webhook, not this endpoint.
"""
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text

from app.services import stripe_billing
from app.services.public_tokens import issue_public_token, revoke_public_token
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _invoiced_job(client, actor, unit_price="100.00"):
    customer = make_customer(client, actor)
    job = make_job(client, actor, customer).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": unit_price},
        headers=auth_headers(actor),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    ).json()
    return job, invoice


def test_token_resolves_the_correct_invoice(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1, max_uses=50,
    )

    resp = client.get(f"/api/v1/public/invoice/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == invoice["id"]
    assert body["total"] == invoice["total"]
    assert len(body["line_items"]) == 1


def test_repeated_reads_do_not_burn_the_token(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1, max_uses=50,
    )

    for _ in range(5):
        assert client.get(f"/api/v1/public/invoice/{token}").status_code == 200

    row = service_db.execute(
        text("SELECT uses FROM public_tokens WHERE token_hash = :h"), {"h": _hash(token)}
    ).first()
    assert row.uses == 0


def test_wrong_purpose_is_a_404(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "estimate_approve",
        ttl_hours=1,
    )
    assert client.get(f"/api/v1/public/invoice/{token}").status_code == 404


def test_wrong_resource_type_is_a_404(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "estimate", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1,
    )
    assert client.get(f"/api/v1/public/invoice/{token}").status_code == 404


def test_expired_token_is_a_404(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1,
    )
    service_db.execute(text("UPDATE public_tokens SET expires_at = now() - interval '1 hour'"))
    service_db.commit()

    assert client.get(f"/api/v1/public/invoice/{token}").status_code == 404


def test_revoked_token_is_a_404(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1,
    )
    revoke_public_token(service_db, _hash(token))

    assert client.get(f"/api/v1/public/invoice/{token}").status_code == 404


def test_an_unknown_token_is_a_404(client):
    assert client.get("/api/v1/public/invoice/not-a-real-token").status_code == 404


def test_checkout_url_is_populated_via_stripe_billing(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    monkeypatch.setattr(
        stripe_billing,
        "create_checkout_session",
        lambda *a, **k: {"id": "cs_test_abc", "url": "https://checkout.stripe.com/test_abc"},
    )

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1, max_uses=50,
    )

    resp = client.get(f"/api/v1/public/invoice/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/test_abc"

    stored = service_db.execute(
        text("SELECT stripe_checkout_session_id FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert stored.stripe_checkout_session_id == "cs_test_abc"


def test_no_checkout_url_when_stripe_is_not_configured(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    monkeypatch.setattr(stripe_billing, "create_checkout_session", lambda *a, **k: None)

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1, max_uses=50,
    )

    resp = client.get(f"/api/v1/public/invoice/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkout_url"] is None


def test_no_checkout_url_for_an_already_voided_invoice(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner))

    calls = []
    monkeypatch.setattr(
        stripe_billing,
        "create_checkout_session",
        lambda *a, **k: calls.append(1) or {"id": "cs_x", "url": "https://x"},
    )

    token = issue_public_token(
        service_db, company_id, "invoice", uuid.UUID(invoice["id"]), "invoice_pay",
        ttl_hours=1, max_uses=50,
    )
    resp = client.get(f"/api/v1/public/invoice/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkout_url"] is None
    assert not calls, "a voided invoice must never mint a new Stripe session"
