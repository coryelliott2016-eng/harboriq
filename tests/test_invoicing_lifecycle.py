"""Invoice lifecycle: draft -> sent -> paid, draft -> void, sent -> void.

Payment itself is applied only via `app.services.invoices.mark_paid_from_webhook`
(exercised in `test_stripe_invoice_webhook.py`); this file drives the
draft/sent/void edges reachable directly through the API.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services import invoices as invoices_service
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _add_line(client, actor, job_id, **fields):
    body = {"kind": "labor", "description": "Diagnosis", "quantity": "1.00", **fields}
    resp = client.post(
        f"/api/v1/jobs/{job_id}/line-items", json=body, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _invoiced_job(client, actor, unit_price="100.00") -> tuple[str, dict]:
    job = _job(client, actor)
    _add_line(client, actor, job, quantity="1.00", unit_price=unit_price)
    resp = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return job, resp.json()


def test_draft_can_be_voided_without_ever_being_sent(client):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["invoice"]["status"] == "void"


def test_voiding_a_draft_frees_its_line_items_for_re_invoicing(client):
    owner = signup(client)
    job_id, invoice = _invoiced_job(client, owner)

    client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner))

    lines = client.get(
        f"/api/v1/jobs/{job_id}/line-items", headers=auth_headers(owner)
    ).json()
    assert lines[0]["invoice_id"] is None
    assert lines[0]["invoiced_at"] is None

    second = client.post(
        "/api/v1/invoices", json={"job_id": job_id}, headers=auth_headers(owner)
    )
    assert second.status_code == 201, second.text


def test_send_moves_draft_to_sent_and_returns_a_pay_url(client):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invoice"]["status"] == "sent"
    assert body["invoice"]["sent_at"] is not None
    assert body["pay_token"]
    assert body["pay_url"] == f"/api/v1/public/invoice/{body['pay_token']}"


def test_sent_invoice_can_still_be_voided(client):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["invoice"]["status"] == "void"


def test_voiding_a_paid_invoice_is_rejected(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner)
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))

    # Apply payment directly via the service (webhook path exercised elsewhere).
    company_id = uuid.UUID(owner["user"]["company_id"])
    service_db.execute(
        text(
            "UPDATE invoices SET stripe_checkout_session_id = 'cs_test_x' WHERE id = :id"
        ),
        {"id": invoice["id"]},
    )
    service_db.commit()
    invoices_service.mark_paid_from_webhook(
        service_db, company_id,
        stripe_checkout_session_id="cs_test_x",
        amount_paid_cents=10000,
    )
    service_db.commit()

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(owner)
    )
    assert resp.status_code == 409, resp.text


def test_a_fully_paid_invoice_shows_paid_and_zero_balance(client, service_db):
    owner = signup(client)
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))

    company_id = uuid.UUID(owner["user"]["company_id"])
    service_db.execute(
        text(
            "UPDATE invoices SET stripe_checkout_session_id = 'cs_test_y' WHERE id = :id"
        ),
        {"id": invoice["id"]},
    )
    service_db.commit()
    invoices_service.mark_paid_from_webhook(
        service_db, company_id,
        stripe_checkout_session_id="cs_test_y",
        amount_paid_cents=10000,
    )
    service_db.commit()

    resp = client.get(f"/api/v1/invoices/{invoice['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paid"
    assert body["balance_due"] == "0.00"
    assert body["paid_at"] is not None


def test_an_unknown_invoice_send_is_a_404(client):
    owner = signup(client)
    resp = client.post(
        f"/api/v1/invoices/{uuid.uuid4()}/send", headers=auth_headers(owner)
    )
    assert resp.status_code == 404


def test_a_technician_cannot_send_or_void_an_invoice(client, service_db):
    from tests.conftest import invite

    owner = signup(client)
    tech = invite(client, owner, "technician")
    _job_id, invoice = _invoiced_job(client, owner)

    assert client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(tech)
    ).status_code == 403
    assert client.post(
        f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(tech)
    ).status_code == 403
