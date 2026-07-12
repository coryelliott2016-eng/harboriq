"""Stripe webhook idempotency — duplicate event applies the side effect once."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.stripe_webhooks import handle_stripe_webhook


def _event(event_id: str, company_id) -> dict:
    return {
        "id": event_id,
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": "in_test_123",
            "amount_paid": 10000,
            "payment_intent": "pi_test_123",
            "metadata": {"company_id": str(company_id)},
        }},
    }


def test_duplicate_event_applied_once(service_db, company_a):
    eid = "evt_" + uuid.uuid4().hex
    payload = _event(eid, company_a)

    handle_stripe_webhook(service_db, eid, payload["type"], payload)
    # outbox receipt should be queued exactly once
    n1 = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type='receipt.send'")
    ).first()[0]
    assert n1 == 1

    # duplicate delivery
    status = handle_stripe_webhook(service_db, eid, payload["type"], payload)
    assert status == 200
    n2 = service_db.execute(
        text("SELECT count(*) FROM outbox_events WHERE event_type='receipt.send'")
    ).first()[0]
    assert n2 == 1, "duplicate event created a second outbox entry"


def test_processed_event_recorded(service_db, company_a):
    eid = "evt_" + uuid.uuid4().hex
    payload = _event(eid, company_a)
    handle_stripe_webhook(service_db, eid, payload["type"], payload)

    row = service_db.execute(
        text("SELECT outcome FROM stripe_processed_events WHERE stripe_event_id=:id"),
        {"id": eid},
    ).first()
    assert row.outcome == "applied"
