"""`POST /webhooks/sms/inbound` (Phase 11) — public, unauthenticated.

Covers: inbound SMS matched to a customer by phone lands in that
customer's thread with `channel='sms'`, unmatched numbers are logged and
dropped (not stored, not a 4xx/5xx), and Twilio signature verification is
skipped-with-a-warning when unconfigured versus enforced once configured.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from sqlalchemy import text

from app.core.config import settings
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer


def _set_customer_phone(service_db, customer_id, phone):
    service_db.execute(
        text("UPDATE customers SET phone = :phone WHERE id = :id"),
        {"phone": phone, "id": customer_id},
    )
    service_db.commit()


def test_inbound_sms_matched_to_customer_lands_in_their_thread(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15559998888")

    resp = client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+15559998888", "Body": "When is my boat ready?"},
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text(
            "SELECT sender_type, channel, body FROM messages WHERE customer_id = :cid"
        ),
        {"cid": customer_id},
    ).first()
    assert row is not None
    assert row.sender_type == "customer"
    assert row.channel == "sms"
    assert row.body == "When is my boat ready?"


def test_inbound_sms_is_visible_in_the_staff_inbox(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15559998888")

    client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+15559998888", "Body": "Any update?"},
    )

    inbox = client.get("/api/v1/messages", headers=auth_headers(owner)).json()
    assert len(inbox) == 1
    assert inbox[0]["channel"] == "sms"
    assert inbox[0]["body"] == "Any update?"


def test_staff_reply_goes_out_via_sms_when_last_inbound_was_sms(
    client, service_db
):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15559998888")

    client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+15559998888", "Body": "Any update?"},
    )

    resp = client.post(
        "/api/v1/messages",
        json={"customer_id": customer_id, "body": "Yes, done by Friday!"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["channel"] == "sms"

    row = service_db.execute(
        text("SELECT payload FROM outbox_events WHERE event_type = 'sms.send'")
    ).first()
    assert row is not None
    assert row.payload["to"] == "+15559998888"
    assert row.payload["body"] == "Yes, done by Friday!"


def test_unmatched_inbound_number_is_dropped_not_stored(client, service_db):
    before = service_db.execute(text("SELECT count(*) FROM messages")).first()[0]

    resp = client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+19995551234", "Body": "Who is this?"},
    )
    assert resp.status_code == 200, resp.text

    after = service_db.execute(text("SELECT count(*) FROM messages")).first()[0]
    assert after == before


def test_signature_verification_is_skipped_with_a_warning_when_unconfigured(
    client, service_db, caplog, monkeypatch
):
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    customer_id = make_customer(client, signup(client))
    _set_customer_phone(service_db, customer_id, "+15559998888")

    with caplog.at_level("WARNING", logger="harboriq.sms"):
        resp = client.post(
            "/api/v1/webhooks/sms/inbound",
            data={"From": "+15559998888", "Body": "no signature at all"},
        )
    assert resp.status_code == 200, resp.text
    assert any("not configured" in rec.message for rec in caplog.records)


def test_signature_is_enforced_once_twilio_is_configured(
    client, service_db, monkeypatch
):
    monkeypatch.setattr(settings, "twilio_auth_token", "test-auth-token")

    resp = client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+15559998888", "Body": "spoofed"},
        headers={"X-Twilio-Signature": "not-a-real-signature"},
    )
    assert resp.status_code == 403


def test_a_valid_signature_is_accepted_once_twilio_is_configured(
    client, service_db, monkeypatch
):
    monkeypatch.setattr(settings, "twilio_auth_token", "test-auth-token")
    customer_id = make_customer(client, signup(client))
    _set_customer_phone(service_db, customer_id, "+15559998888")

    url = "http://testserver/api/v1/webhooks/sms/inbound"
    params = {"From": "+15559998888", "Body": "hi"}
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(b"test-auth-token", data.encode(), hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode()

    resp = client.post(
        "/api/v1/webhooks/sms/inbound",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )
    assert resp.status_code == 200, resp.text


def test_unconfigured_signature_in_production_hard_rejects(
    client, service_db, monkeypatch
):
    """Security Core Prompt v1.0 (M-1 fix): outside development, an
    unconfigured TWILIO_AUTH_TOKEN must never silently allow unverified
    inbound SMS -- it must hard-reject instead."""
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "app_env", "production")

    resp = client.post(
        "/api/v1/webhooks/sms/inbound",
        data={"From": "+15559998888", "Body": "should be rejected"},
    )
    assert resp.status_code == 503


def test_unconfigured_signature_in_development_still_accepts_with_warning(
    client, service_db, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "app_env", "development")
    customer_id = make_customer(client, signup(client))
    _set_customer_phone(service_db, customer_id, "+15559998888")

    with caplog.at_level("WARNING", logger="harboriq.sms"):
        resp = client.post(
            "/api/v1/webhooks/sms/inbound",
            data={"From": "+15559998888", "Body": "dev only"},
        )
    assert resp.status_code == 200, resp.text
