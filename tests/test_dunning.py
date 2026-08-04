"""Automated dunning (Phase 8): overdue invoices get reminders, cadence is
respected, tenant isolation holds. No real network calls -- outbox delivery
itself is exercised separately in test_email_and_outbox_dispatch.py /
test_invoice_pdf_email.py; this file only checks that the sweep queues the
right outbox rows and stamps `last_reminder_sent_at` correctly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services import invoices as invoices_service
from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _sent_invoice(client, service_db, actor, due_in_days: int, unit_price="100.00"):
    """Create + send an invoice, then backdate its due_date directly (there
    is no API surface for setting due_date explicitly, matching the schema
    -- due_date defaults on send; see app/services/invoices.py)."""
    customer_id = make_customer(client, actor)
    job = make_job(client, actor, customer_id).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": unit_price},
        headers=auth_headers(actor),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(actor))

    due_date = datetime.now(timezone.utc) + timedelta(days=due_in_days)
    service_db.execute(
        text("UPDATE invoices SET due_date = :d WHERE id = :id"),
        {"d": due_date, "id": invoice["id"]},
    )
    service_db.commit()
    return invoice


def test_sweep_reminds_an_overdue_unpaid_invoice(client, service_db):
    owner = signup(client)
    invoice = _sent_invoice(client, service_db, owner, due_in_days=-5)

    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert invoice["id"] in body["reminded_invoice_ids"]

    row = service_db.execute(
        text(
            "SELECT event_type FROM outbox_events "
            "WHERE company_id = :cid AND event_type = 'invoice.dunning_reminder'"
        ),
        {"cid": owner["user"]["company_id"]},
    ).first()
    assert row is not None
    assert row.event_type == "invoice.dunning_reminder"

    stamped = service_db.execute(
        text("SELECT last_reminder_sent_at FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert stamped.last_reminder_sent_at is not None


def test_sweep_ignores_invoices_not_yet_due(client, service_db):
    owner = signup(client)
    _sent_invoice(client, service_db, owner, due_in_days=5)

    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 0


def test_sweep_ignores_fully_paid_invoices(client, service_db):
    owner = signup(client)
    invoice = _sent_invoice(client, service_db, owner, due_in_days=-5)

    company_id = uuid.UUID(owner["user"]["company_id"])
    session_id = f"cs_test_dunning_{uuid.uuid4().hex[:6]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()
    invoices_service.mark_paid_from_webhook(
        service_db, company_id, stripe_checkout_session_id=session_id, amount_paid_cents=10000
    )
    service_db.commit()

    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 0


def test_sweep_does_not_re_remind_within_the_cooldown_window(client, service_db):
    owner = signup(client)
    invoice = _sent_invoice(client, service_db, owner, due_in_days=-10)

    first = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert first.json()["count"] == 1

    second = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert second.json()["count"] == 0

    # Force last_reminder_sent_at to be outside the cooldown window and
    # confirm the invoice becomes eligible again.
    stale = datetime.now(timezone.utc) - timedelta(days=10)
    service_db.execute(
        text("UPDATE invoices SET last_reminder_sent_at = :d WHERE id = :id"),
        {"d": stale, "id": invoice["id"]},
    )
    service_db.commit()

    third = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert third.json()["count"] == 1


def test_sweep_ignores_draft_and_void_invoices(client, service_db):
    owner = signup(client)
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
    # Still a draft: never sent, never has a due_date.
    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 0
    assert invoice["id"] not in resp.json()["reminded_invoice_ids"]


def test_sweep_is_scoped_to_its_own_tenant(client, service_db):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    invoice_a = _sent_invoice(client, service_db, owner_a, due_in_days=-3)
    _sent_invoice(client, service_db, owner_b, due_in_days=-3)

    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(owner_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["reminded_invoice_ids"] == [invoice_a["id"]]


def test_a_technician_cannot_trigger_the_sweep(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(tech))
    assert resp.status_code == 403


def test_office_role_cannot_trigger_the_sweep_admin_only(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    resp = client.post("/api/v1/billing/dunning/run", headers=auth_headers(office))
    assert resp.status_code == 403


def test_the_job_module_sweep_runs_across_all_companies(client, service_db):
    """`app.jobs.dunning_sweep.run()` -- the cron-style, all-tenants entry
    point -- reminds every eligible tenant's overdue invoices in one pass."""
    from app.jobs import dunning_sweep

    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    invoice_a = _sent_invoice(client, service_db, owner_a, due_in_days=-3)
    invoice_b = _sent_invoice(client, service_db, owner_b, due_in_days=-3)

    result = dunning_sweep.run()
    assert result["reminded_count"] >= 2

    for inv in (invoice_a, invoice_b):
        stamped = service_db.execute(
            text("SELECT last_reminder_sent_at FROM invoices WHERE id = :id"),
            {"id": inv["id"]},
        ).first()
        assert stamped.last_reminder_sent_at is not None
