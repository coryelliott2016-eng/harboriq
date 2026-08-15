"""Stripe Billing subscription reconciliation (HarborIQ's OWN SaaS charge to
the shop for using the platform) — distinct from a shop's customer invoices,
which `tests/test_stripe_invoice_webhook.py` covers.

Exercises `_on_subscription_payment_succeeded` / `_on_subscription_payment_failed`
resolving the local `subscriptions` row by `stripe_subscription_id` and
reconciling `active` / `past_due` status.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.stripe_webhooks import handle_stripe_webhook


def _make_plan(db, code="starter"):
    row = db.execute(
        text(
            """
            INSERT INTO subscription_plans (code, name, monthly_price, annual_price, seat_limit)
            VALUES (:code, :name, 49.00, 490.00, 5)
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
            RETURNING id
            """
        ),
        {"code": code, "name": code.title()},
    ).first()
    db.commit()
    return row.id


def _make_subscription(db, company_id, plan_id, stripe_subscription_id, status="active"):
    row = db.execute(
        text(
            """
            INSERT INTO subscriptions (company_id, plan_id, status, stripe_subscription_id)
            VALUES (:cid, :pid, :status, :sid)
            RETURNING id
            """
        ),
        {"cid": company_id, "pid": plan_id, "status": status, "sid": stripe_subscription_id},
    ).first()
    db.commit()
    return row.id


def _invoice_event(event_id, event_type, company_id, subscription_id, period_end=None):
    obj = {
        "id": "in_" + uuid.uuid4().hex[:12],
        "amount_paid": 4900,
        "amount_due": 4900,
        "payment_intent": "pi_" + uuid.uuid4().hex[:12],
        "subscription": subscription_id,
        "metadata": {"company_id": str(company_id)},
    }
    if period_end is not None:
        obj["period_end"] = period_end
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def test_payment_succeeded_activates_subscription_and_clears_past_due(service_db, company_a):
    plan_id = _make_plan(service_db)
    sub_stripe_id = "sub_" + uuid.uuid4().hex[:12]
    _make_subscription(service_db, company_a, plan_id, sub_stripe_id, status="past_due")

    eid = "evt_" + uuid.uuid4().hex
    period_end = 1_800_000_000
    event = _invoice_event(eid, "invoice.payment_succeeded", company_a, sub_stripe_id, period_end)
    status_code = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert status_code == 200

    row = service_db.execute(
        text(
            "SELECT status, canceled_at, extract(epoch from current_period_end) AS cpe "
            "FROM subscriptions WHERE stripe_subscription_id = :sid"
        ),
        {"sid": sub_stripe_id},
    ).first()
    assert row.status == "active"
    assert row.canceled_at is None
    assert int(row.cpe) == period_end

    # Receipt is still queued exactly as before.
    n = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type = 'receipt.send'")
    ).first()[0]
    assert n == 1


def test_payment_failed_marks_subscription_past_due(service_db, company_a):
    plan_id = _make_plan(service_db)
    sub_stripe_id = "sub_" + uuid.uuid4().hex[:12]
    _make_subscription(service_db, company_a, plan_id, sub_stripe_id, status="active")

    eid = "evt_" + uuid.uuid4().hex
    event = _invoice_event(eid, "invoice.payment_failed", company_a, sub_stripe_id)
    status_code = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert status_code == 200

    row = service_db.execute(
        text("SELECT status FROM subscriptions WHERE stripe_subscription_id = :sid"),
        {"sid": sub_stripe_id},
    ).first()
    assert row.status == "past_due"

    n = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type = 'billing.payment_failed'")
    ).first()[0]
    assert n == 1


def test_payment_failed_does_not_resurrect_a_canceled_subscription(service_db, company_a):
    plan_id = _make_plan(service_db)
    sub_stripe_id = "sub_" + uuid.uuid4().hex[:12]
    _make_subscription(service_db, company_a, plan_id, sub_stripe_id, status="canceled")

    eid = "evt_" + uuid.uuid4().hex
    event = _invoice_event(eid, "invoice.payment_failed", company_a, sub_stripe_id)
    handle_stripe_webhook(service_db, eid, event["type"], event)

    row = service_db.execute(
        text("SELECT status FROM subscriptions WHERE stripe_subscription_id = :sid"),
        {"sid": sub_stripe_id},
    ).first()
    assert row.status == "canceled", "a canceled subscription must not be reopened by a late failed invoice"


def test_payment_succeeded_with_unknown_subscription_id_is_a_safe_no_op(service_db, company_a):
    """No matching local subscription row (e.g. reconciliation lag, or a plan
    change mid-cycle) must not raise — the receipt still queues."""
    eid = "evt_" + uuid.uuid4().hex
    event = _invoice_event(eid, "invoice.payment_succeeded", company_a, "sub_does_not_exist")
    status_code = handle_stripe_webhook(service_db, eid, event["type"], event)
    assert status_code == 200

    n = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type = 'receipt.send'")
    ).first()[0]
    assert n == 1


def test_payment_failed_does_not_cross_tenant(service_db, company_a, company_b):
    """A subscription belonging to company_b must not be touched by an event
    whose metadata claims company_a — RLS via current_setting('app.current_company_id')."""
    plan_id = _make_plan(service_db)
    sub_stripe_id = "sub_" + uuid.uuid4().hex[:12]
    _make_subscription(service_db, company_b, plan_id, sub_stripe_id, status="active")

    eid = "evt_" + uuid.uuid4().hex
    event = _invoice_event(eid, "invoice.payment_failed", company_a, sub_stripe_id)
    handle_stripe_webhook(service_db, eid, event["type"], event)

    row = service_db.execute(
        text("SELECT status FROM subscriptions WHERE stripe_subscription_id = :sid"),
        {"sid": sub_stripe_id},
    ).first()
    assert row.status == "active", "cross-tenant event must not modify another company's subscription"
