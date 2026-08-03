"""Stripe webhook -> marine-shop customer invoice payment.

Distinct from `tests/test_stripe_webhook_idempotency.py`, which exercises the
UNRELATED Stripe Billing subscription-invoice path
(`invoice.payment_succeeded` -> `_on_subscription_payment_succeeded`, still a
stub). This file drives `checkout.session.completed` with
`metadata.kind == "invoice_payment"`, which is what Phase 3 implements:
`_on_invoice_payment_completed` -> `invoices.mark_paid_from_webhook`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.stripe_webhooks import handle_stripe_webhook
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


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
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(actor))
    return job, invoice


def _checkout_completed_event(event_id, company_id, invoice_id, session_id,
                              amount_total_cents):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "object": "checkout.session",
            "amount_total": amount_total_cents,
            "payment_intent": f"pi_{uuid.uuid4().hex[:12]}",
            "metadata": {
                "company_id": str(company_id),
                "invoice_id": str(invoice_id),
                "kind": "invoice_payment",
            },
        }},
    }


def _session_id_for(service_db, invoice_id) -> str:
    row = service_db.execute(
        text("SELECT stripe_checkout_session_id FROM invoices WHERE id = :id"),
        {"id": invoice_id},
    ).first()
    return row.stripe_checkout_session_id


def test_full_payment_marks_the_invoice_paid_and_writes_a_payment_row(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")

    # `send` may or may not have created a real Stripe session (no API key in
    # tests) -- stamp one directly so the webhook has something to resolve by,
    # mirroring how `create_checkout_session` would have populated it.
    session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()

    eid = "evt_" + uuid.uuid4().hex
    event = _checkout_completed_event(eid, company_id, invoice["id"], session_id, 10000)
    status_code = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert status_code == 200

    row = service_db.execute(
        text("SELECT status, amount_paid, balance_due, paid_at FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert row.status == "paid"
    assert str(row.amount_paid) == "100.00"
    assert str(row.balance_due) == "0.00"
    assert row.paid_at is not None

    payments = service_db.execute(
        text("SELECT count(*) FROM payments WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()[0]
    assert payments == 1


def test_partial_payment_results_in_partial_status(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")

    session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()

    eid = "evt_" + uuid.uuid4().hex
    event = _checkout_completed_event(eid, company_id, invoice["id"], session_id, 4000)
    handle_stripe_webhook(service_db, eid, event["type"], event)

    row = service_db.execute(
        text("SELECT status, amount_paid, balance_due FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert row.status == "partial"
    assert str(row.amount_paid) == "40.00"
    assert str(row.balance_due) == "60.00"


def test_duplicate_event_delivery_does_not_double_pay(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")

    session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()

    eid = "evt_" + uuid.uuid4().hex
    event = _checkout_completed_event(eid, company_id, invoice["id"], session_id, 10000)

    first = handle_stripe_webhook(service_db, eid, event["type"], event)
    second = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert first == 200
    assert second == 200

    row = service_db.execute(
        text("SELECT amount_paid FROM invoices WHERE id = :id"), {"id": invoice["id"]}
    ).first()
    assert str(row.amount_paid) == "100.00", "duplicate delivery must not double-apply payment"

    payments = service_db.execute(
        text("SELECT count(*) FROM payments WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()[0]
    assert payments == 1, "duplicate event created a second payment row"


def test_subscription_invoice_payment_succeeded_is_unaffected(service_db, company_a):
    """The pre-existing Stripe Billing subscription path (renamed to
    `_on_subscription_payment_succeeded`) must remain wired to
    `invoice.payment_succeeded` and keep queuing a receipt, unmodified."""
    eid = "evt_" + uuid.uuid4().hex
    payload = {
        "id": eid,
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": "in_test_999",
            "amount_paid": 5000,
            "payment_intent": "pi_test_999",
            "metadata": {"company_id": str(company_a)},
        }},
    }
    status_code = handle_stripe_webhook(service_db, eid, payload["type"], payload)
    assert status_code == 200

    n = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type = 'receipt.send'")
    ).first()[0]
    assert n == 1
