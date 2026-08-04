"""Stripe Connect onboarding/status (Phase 8). Stripe is always mocked via
`monkeypatch.setattr(stripe_billing, ...)` -- no real network calls.
"""
from __future__ import annotations


from sqlalchemy import text

from app.services import stripe_billing
from tests.conftest import auth_headers, invite, signup


def test_starting_onboarding_creates_an_account_and_returns_a_link(
    client, service_db, monkeypatch
):
    owner = signup(client)
    monkeypatch.setattr(
        stripe_billing,
        "create_connect_account_and_onboarding_link",
        lambda company_id, existing_account_id, return_url, refresh_url: {
            "account_id": "acct_test_123",
            "url": "https://connect.stripe.com/setup/test_123",
        },
    )

    resp = client.post(
        "/api/v1/billing/connect/onboarding-link", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account_id"] == "acct_test_123"
    assert body["onboarding_url"] == "https://connect.stripe.com/setup/test_123"

    stored = service_db.execute(
        text("SELECT stripe_connect_account_id FROM companies WHERE id = :id"),
        {"id": owner["user"]["company_id"]},
    ).first()
    assert stored.stripe_connect_account_id == "acct_test_123"


def test_onboarding_reuses_an_existing_account_id(client, service_db, monkeypatch):
    owner = signup(client)
    company_id = owner["user"]["company_id"]
    service_db.execute(
        text("UPDATE companies SET stripe_connect_account_id = 'acct_existing' WHERE id = :id"),
        {"id": company_id},
    )
    service_db.commit()

    seen_existing = []
    monkeypatch.setattr(
        stripe_billing,
        "create_connect_account_and_onboarding_link",
        lambda company_id, existing_account_id, return_url, refresh_url: (
            seen_existing.append(existing_account_id)
            or {"account_id": existing_account_id, "url": "https://connect.stripe.com/resume"}
        ),
    )

    resp = client.post(
        "/api/v1/billing/connect/onboarding-link", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert seen_existing == ["acct_existing"]
    assert resp.json()["account_id"] == "acct_existing"


def test_onboarding_returns_502_when_stripe_is_not_configured(client, monkeypatch):
    owner = signup(client)
    monkeypatch.setattr(
        stripe_billing,
        "create_connect_account_and_onboarding_link",
        lambda *a, **k: None,
    )
    resp = client.post(
        "/api/v1/billing/connect/onboarding-link", headers=auth_headers(owner)
    )
    assert resp.status_code == 502, resp.text


def test_status_reports_not_connected_when_no_account_id_on_file(client):
    owner = signup(client)
    resp = client.get("/api/v1/billing/connect/status", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "connected": False,
        "account_id": None,
        "charges_enabled": False,
        "details_submitted": False,
    }


def test_status_reports_charges_enabled_once_onboarding_completes(
    client, service_db, monkeypatch
):
    owner = signup(client)
    company_id = owner["user"]["company_id"]
    service_db.execute(
        text("UPDATE companies SET stripe_connect_account_id = 'acct_done' WHERE id = :id"),
        {"id": company_id},
    )
    service_db.commit()

    monkeypatch.setattr(
        stripe_billing,
        "get_connect_account_status",
        lambda account_id: {"charges_enabled": True, "details_submitted": True},
    )

    resp = client.get("/api/v1/billing/connect/status", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert body["account_id"] == "acct_done"
    assert body["charges_enabled"] is True
    assert body["details_submitted"] is True


def test_status_degrades_gracefully_when_stripe_is_unreachable(
    client, service_db, monkeypatch
):
    owner = signup(client)
    company_id = owner["user"]["company_id"]
    service_db.execute(
        text("UPDATE companies SET stripe_connect_account_id = 'acct_flaky' WHERE id = :id"),
        {"id": company_id},
    )
    service_db.commit()
    monkeypatch.setattr(stripe_billing, "get_connect_account_status", lambda account_id: None)

    resp = client.get("/api/v1/billing/connect/status", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert body["charges_enabled"] is False


def test_a_technician_cannot_start_onboarding_or_view_status(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    assert client.post(
        "/api/v1/billing/connect/onboarding-link", headers=auth_headers(tech)
    ).status_code == 403
    assert client.get(
        "/api/v1/billing/connect/status", headers=auth_headers(tech)
    ).status_code == 403


def test_office_role_cannot_start_onboarding_admin_only(client):
    """require_admin (owner/admin) gates Connect, unlike refunds/reports
    which use require_operations (owner/admin/office)."""
    owner = signup(client)
    office = invite(client, owner, "office")
    resp = client.post(
        "/api/v1/billing/connect/onboarding-link", headers=auth_headers(office)
    )
    assert resp.status_code == 403, resp.text


def test_checkout_session_uses_the_connect_account_when_onboarded(
    client, service_db, monkeypatch
):
    """Once a tenant has completed Connect onboarding, invoice checkout
    sessions should be created against their connected account (direct
    charge pattern) -- the fallback path is covered by the pre-existing
    `test_public_invoice_pay.py` tests, which never set a Connect account."""
    from tests.test_crm_jobs import make_customer, make_job

    owner = signup(client)
    company_id = owner["user"]["company_id"]
    service_db.execute(
        text("UPDATE companies SET stripe_connect_account_id = 'acct_direct' WHERE id = :id"),
        {"id": company_id},
    )
    service_db.commit()

    customer_id = make_customer(client, owner)
    job = make_job(client, owner, customer_id).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": "50.00"},
        headers=auth_headers(owner),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(owner)
    ).json()

    seen_accounts = []
    monkeypatch.setattr(
        stripe_billing,
        "create_checkout_session",
        lambda *a, stripe_account=None, **k: (
            seen_accounts.append(stripe_account)
            or {"id": "cs_connect_1", "url": "https://checkout.stripe.com/connect_1"}
        ),
    )

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert seen_accounts == ["acct_direct"]
