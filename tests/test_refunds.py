"""Refunds and partial refunds (Phase 8): full/partial flows, state
transitions, role gating, tenant isolation. Stripe is always mocked via
`monkeypatch.setattr(stripe_billing, "create_refund", ...)` -- no real
network calls, matching the convention already established in
`tests/test_public_invoice_pay.py` for `create_checkout_session`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.services import invoices as invoices_service
from app.services import stripe_billing
from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _add_line(client, actor, job_id, **fields):
    body = {"kind": "labor", "description": "Diagnosis", "quantity": "1.00", **fields}
    resp = client.post(
        f"/api/v1/jobs/{job_id}/line-items", json=body, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _invoiced_job(client, actor, unit_price="100.00", customer_id=None) -> tuple[str, dict]:
    customer_id = customer_id or make_customer(client, actor)
    job = make_job(client, actor, customer_id).json()["id"]
    _add_line(client, actor, job, quantity="1.00", unit_price=unit_price)
    resp = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return job, resp.json()


def _pay(client, service_db, owner, invoice, cents, session_suffix="a"):
    """Send + mark-paid (or partially paid) an invoice via the webhook path,
    exactly like `test_invoicing_lifecycle.py` already does."""
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))
    company_id = uuid.UUID(owner["user"]["company_id"])
    session_id = f"cs_test_refund_{session_suffix}_{uuid.uuid4().hex[:6]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()
    invoices_service.mark_paid_from_webhook(
        service_db, company_id,
        stripe_checkout_session_id=session_id,
        amount_paid_cents=cents,
    )
    service_db.commit()


def _mock_refund(monkeypatch, refund_id="re_test_123"):
    calls = []
    monkeypatch.setattr(
        stripe_billing,
        "create_refund",
        lambda **kwargs: calls.append(kwargs) or {"id": refund_id},
    )
    return calls


def test_full_refund_of_a_paid_invoice(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    calls = _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"reason": "customer request"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invoice"]["status"] == "refunded"
    assert body["refund"]["amount"] == "100.00"
    assert body["refund"]["stripe_refund_id"] == "re_test_123"
    assert body["refund"]["reason"] == "customer request"
    assert len(calls) == 1
    assert calls[0]["amount"] == invoices_service._quantize(Decimal("100"))


def test_partial_refund_of_a_paid_invoice(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "40.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invoice"]["status"] == "partially_refunded"
    assert body["refund"]["amount"] == "40.00"


def test_a_second_partial_refund_can_complete_the_remainder(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch)

    first = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "40.00"},
        headers=auth_headers(owner),
    )
    assert first.status_code == 200, first.text
    assert first.json()["invoice"]["status"] == "partially_refunded"

    second = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "60.00"},
        headers=auth_headers(owner),
    )
    assert second.status_code == 200, second.text
    assert second.json()["invoice"]["status"] == "refunded"


def test_refunding_more_than_the_remaining_balance_is_rejected(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch)

    client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "60.00"},
        headers=auth_headers(owner),
    )
    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        json={"amount": "60.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409, resp.text


def test_refunding_a_partially_paid_invoice_is_allowed(client, service_db, monkeypatch):
    """A deposit ('partial' status) is refundable even before the balance is
    fully paid -- see InvoiceSM.transitions["partial"]. Refunding the whole
    deposit still lands on `partially_refunded`, not `refunded`: the
    customer never paid the invoice in full, so `refunded` (implying a
    fully-paid-then-fully-returned invoice) would be misleading -- the
    invoice still has an outstanding, never-paid balance."""
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 4000)  # deposit only -> "partial"

    check = client.get(f"/api/v1/invoices/{invoice['id']}", headers=auth_headers(owner))
    assert check.json()["status"] == "partial"

    _mock_refund(monkeypatch)
    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["invoice"]["status"] == "partially_refunded"
    assert resp.json()["refund"]["amount"] == "40.00"


def test_refunding_an_unpaid_invoice_is_rejected(client, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(owner)
    )
    assert resp.status_code == 409, resp.text


def test_refund_failure_from_stripe_returns_502_and_does_not_change_status(
    client, service_db, monkeypatch
):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    monkeypatch.setattr(stripe_billing, "create_refund", lambda **kwargs: None)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(owner)
    )
    assert resp.status_code == 502, resp.text

    check = client.get(f"/api/v1/invoices/{invoice['id']}", headers=auth_headers(owner))
    assert check.json()["status"] == "paid"


def test_a_technician_cannot_issue_a_refund(client, service_db, monkeypatch):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(tech)
    )
    assert resp.status_code == 403, resp.text


def test_office_role_can_issue_a_refund(client, service_db, monkeypatch):
    """require_operations includes office, unlike require_admin."""
    owner = signup(client)
    office = invite(client, owner, "office")
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(office)
    )
    assert resp.status_code == 200, resp.text


def test_refund_is_scoped_to_its_own_tenant(client, service_db, monkeypatch):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    _job_id, invoice = _invoiced_job(client, owner_a, unit_price="100.00")
    _pay(client, service_db, owner_a, invoice, 10000)
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(owner_b)
    )
    assert resp.status_code == 404, resp.text


def test_refunding_an_unknown_invoice_is_a_404(client, monkeypatch):
    owner = signup(client)
    _mock_refund(monkeypatch)
    resp = client.post(
        f"/api/v1/invoices/{uuid.uuid4()}/refund", headers=auth_headers(owner)
    )
    assert resp.status_code == 404


def test_refund_row_is_persisted_with_created_by(client, service_db, monkeypatch):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    _pay(client, service_db, owner, invoice, 10000)
    _mock_refund(monkeypatch, refund_id="re_persist_1")

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text("SELECT stripe_refund_id, created_by FROM refunds WHERE invoice_id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert row.stripe_refund_id == "re_persist_1"
    assert str(row.created_by) == owner["user"]["id"]
