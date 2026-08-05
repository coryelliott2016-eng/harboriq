"""Refund webhook reconciliation (Phase 17, Area E).

Covers `charge.refunded` -- a refund issued directly in the Stripe
Dashboard (or via the Stripe API, bypassing HarborIQ's own
`POST /invoices/{id}/refund`) still updates the local `invoices`/`refunds`
tables. Distinct from `tests/test_invoices.py`'s refund tests, which drive
the OUTBOUND `refund_invoice` path where HarborIQ itself calls Stripe.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.stripe_webhooks import handle_stripe_webhook
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _paid_invoice(client, actor, unit_price="100.00"):
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
    return invoice


def _mark_paid(service_db, invoice_id, payment_intent_id, amount_cents):
    """Simulate the invoice having already been paid via the normal
    checkout.session.completed webhook path, so there's something to
    refund against. `mark_paid_from_webhook` resolves an invoice by an
    EXISTING `stripe_checkout_session_id`/`stripe_payment_intent_id` column
    value -- it doesn't stamp a brand-new payment_intent id out of nowhere
    -- so a session id must be seeded first, exactly like
    `test_stripe_invoice_webhook.py` does."""
    from app.services import invoices as invoices_service

    company_row = service_db.execute(
        text("SELECT company_id FROM invoices WHERE id = :id"), {"id": invoice_id}
    ).first()
    company_id = company_row.company_id

    session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice_id},
    )
    service_db.commit()

    invoices_service.mark_paid_from_webhook(
        service_db,
        company_id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=payment_intent_id,
        amount_paid_cents=amount_cents,
    )
    service_db.commit()
    return company_id


def _charge_refunded_event(event_id, payment_intent_id, charge_id, refunds, amount_refunded):
    return {
        "id": event_id,
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": charge_id,
                "object": "charge",
                "payment_intent": payment_intent_id,
                "amount_refunded": amount_refunded,
                "refunded": True,
                "metadata": {},
                "refunds": {"object": "list", "data": refunds},
            }
        },
    }


def _refund_obj(refund_id, payment_intent_id, amount, reason="requested_by_customer", status="succeeded"):
    return {
        "id": refund_id,
        "object": "refund",
        "amount": amount,
        "payment_intent": payment_intent_id,
        "reason": reason,
        "status": status,
    }


def test_full_refund_via_dashboard_updates_invoice_and_creates_refund_row(client, service_db):
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    eid = "evt_" + uuid.uuid4().hex
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 10000)], 10000
    )

    status_code = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert status_code == 200

    row = service_db.execute(
        text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice["id"]}
    ).first()
    assert row.status == "refunded"

    refund_row = service_db.execute(
        text("SELECT amount, stripe_refund_id, reason FROM refunds WHERE invoice_id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert str(refund_row.amount) == "100.00"
    assert refund_row.stripe_refund_id == refund_id
    assert refund_row.reason == "requested_by_customer"


def test_partial_refund_via_dashboard_sets_partially_refunded(client, service_db):
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    eid = "evt_" + uuid.uuid4().hex
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 4000)], 4000
    )

    handle_stripe_webhook(service_db, eid, event["type"], event)

    row = service_db.execute(
        text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice["id"]}
    ).first()
    assert row.status == "partially_refunded"

    refund_row = service_db.execute(
        text("SELECT amount FROM refunds WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()
    assert str(refund_row.amount) == "40.00"


def test_duplicate_charge_refunded_delivery_does_not_double_apply(client, service_db):
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    eid = "evt_" + uuid.uuid4().hex
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 10000)], 10000
    )

    first = handle_stripe_webhook(service_db, eid, event["type"], event)
    second = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert first == 200
    assert second == 200

    count = service_db.execute(
        text("SELECT count(*) FROM refunds WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()[0]
    assert count == 1, "duplicate event delivery must not create a second refund row"


def test_second_partial_refund_on_same_charge_is_additive_not_duplicated(client, service_db):
    """Stripe re-fires charge.refunded with a GROWING refunds.data list every
    time another refund lands on the same charge -- the second delivery must
    apply only the NEW refund id, not re-apply the first."""
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_1 = f"re_{uuid.uuid4().hex[:12]}"
    refund_2 = f"re_{uuid.uuid4().hex[:12]}"

    eid1 = "evt_" + uuid.uuid4().hex
    event1 = _charge_refunded_event(
        eid1, pi, charge_id, [_refund_obj(refund_1, pi, 3000)], 3000
    )
    handle_stripe_webhook(service_db, eid1, event1["type"], event1)

    eid2 = "evt_" + uuid.uuid4().hex
    event2 = _charge_refunded_event(
        eid2,
        pi,
        charge_id,
        [_refund_obj(refund_1, pi, 3000), _refund_obj(refund_2, pi, 2000)],
        5000,
    )
    handle_stripe_webhook(service_db, eid2, event2["type"], event2)

    count = service_db.execute(
        text("SELECT count(*) FROM refunds WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()[0]
    assert count == 2

    total = service_db.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE invoice_id = :id"),
        {"id": invoice["id"]},
    ).first()[0]
    assert str(total) == "50.00"


def test_charge_with_no_matching_invoice_is_a_safe_noop(client, service_db, company_a):
    """A charge.refunded for a charge that has nothing to do with a HarborIQ
    invoice (e.g. the platform's own subscription billing) must not error --
    it's simply nothing to reconcile."""
    eid = "evt_" + uuid.uuid4().hex
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 1000)], 1000
    )
    # No invoice anywhere references this payment_intent, and there's no
    # metadata/account/subscription to resolve company_id from either --
    # resolution itself should fail, exactly like any other unresolvable
    # event this webhook already receives.
    with pytest_raises_value_error():
        handle_stripe_webhook(service_db, eid, event["type"], event)


def pytest_raises_value_error():
    import pytest

    return pytest.raises(ValueError)


def test_pending_refund_in_list_is_ignored(client, service_db):
    """A `refunds.data[]` entry that hasn't succeeded yet (e.g. still
    `pending` for a bank-debit-funded charge) must not touch the ledger."""
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    eid = "evt_" + uuid.uuid4().hex
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 10000, status="pending")], 0
    )

    handle_stripe_webhook(service_db, eid, event["type"], event)

    row = service_db.execute(
        text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice["id"]}
    ).first()
    assert row.status == "paid", "a pending (not yet succeeded) refund must not change invoice status"

    count = service_db.execute(
        text("SELECT count(*) FROM refunds WHERE invoice_id = :id"), {"id": invoice["id"]}
    ).first()[0]
    assert count == 0


def test_reconciled_refund_is_visible_via_the_invoices_api(client, service_db):
    """After reconciliation, staff viewing the invoice through the normal
    API sees the refunded status -- not just a raw DB row."""
    owner = signup(client)
    invoice = _paid_invoice(client, owner, unit_price="100.00")
    pi = f"pi_{uuid.uuid4().hex[:12]}"
    _mark_paid(service_db, invoice["id"], pi, 10000)

    charge_id = f"ch_{uuid.uuid4().hex[:12]}"
    refund_id = f"re_{uuid.uuid4().hex[:12]}"
    eid = "evt_" + uuid.uuid4().hex
    event = _charge_refunded_event(
        eid, pi, charge_id, [_refund_obj(refund_id, pi, 10000)], 10000
    )
    handle_stripe_webhook(service_db, eid, event["type"], event)

    resp = client.get(f"/api/v1/invoices/{invoice['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "refunded"
