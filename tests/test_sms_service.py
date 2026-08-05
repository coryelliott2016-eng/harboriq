"""Outbound SMS transport (`app/services/sms.py`) and its `sms.send` outbox
event type.

Mirrors `tests/test_email_and_outbox_dispatch.py`'s conventions exactly:
no real network calls (`httpx.post` is monkeypatched), console-fallback
when Twilio is unconfigured, a real-send path once all three Twilio env
vars are set, and `outbox.dispatch_pending` correctly routing `sms.send`
rows to `sms.send_sms` instead of email.
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import outbox, sms


# ---------------------------------------------------------------------------
# app/services/sms.py
# ---------------------------------------------------------------------------
def test_console_fallback_when_twilio_is_unconfigured(monkeypatch, caplog):
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "twilio_from_number", "")
    calls = []
    monkeypatch.setattr(sms.httpx, "post", lambda *a, **kw: calls.append((a, kw)))

    with caplog.at_level("INFO", logger="harboriq.sms"):
        ok = sms.send_sms("+15551234567", "Your tech is on the way")

    assert ok is True
    assert calls == []  # httpx was never touched
    assert any("console-transport" in rec.message for rec in caplog.records)


def test_is_configured_requires_all_three_twilio_settings(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550001111")
    assert sms.is_configured() is False

    monkeypatch.setattr(settings, "twilio_auth_token", "secret")
    assert sms.is_configured() is True


class _FakeResponse:
    def __init__(self, status_code=201):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=self)


def test_real_send_when_twilio_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550001111")

    calls = []

    def _fake_post(url, data=None, auth=None, timeout=None):
        calls.append({"url": url, "data": data, "auth": auth})
        return _FakeResponse(201)

    monkeypatch.setattr(sms.httpx, "post", _fake_post)

    ok = sms.send_sms("+15551234567", "Your tech is on the way")

    assert ok is True
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert call["data"]["To"] == "+15551234567"
    assert call["data"]["From"] == "+15550001111"
    assert call["data"]["Body"] == "Your tech is on the way"
    assert call["auth"] == ("AC123", "secret-token")


def test_real_send_failure_is_caught_and_returns_false(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550001111")

    def _boom(*a, **kw):
        return _FakeResponse(500)

    monkeypatch.setattr(sms.httpx, "post", _boom)

    ok = sms.send_sms("+15551234567", "Body")
    assert ok is False


def test_real_send_network_error_is_caught_and_returns_false(monkeypatch):
    import httpx as httpx_module

    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550001111")

    def _boom(*a, **kw):
        raise httpx_module.ConnectError("dns failure")

    monkeypatch.setattr(sms.httpx, "post", _boom)

    ok = sms.send_sms("+15551234567", "Body")
    assert ok is False


# ---------------------------------------------------------------------------
# app/services/outbox.py dispatch_pending routing to SMS
# ---------------------------------------------------------------------------
def _enqueue_and_commit(app_db, company_id, event_type, payload):
    with tenant_context(app_db, company_id):
        outbox.enqueue(app_db, company_id, event_type, payload)
        app_db.commit()


def test_dispatch_routes_sms_send_events_to_send_sms_not_email(
    monkeypatch, app_db, service_db, company_a
):
    from app.services import email

    email_calls = []
    sms_calls = []
    monkeypatch.setattr(
        email, "send_email",
        lambda *a, **kw: email_calls.append(a) or True,
    )
    monkeypatch.setattr(
        sms, "send_sms",
        lambda to, body: sms_calls.append((to, body)) or True,
    )

    _enqueue_and_commit(
        app_db, company_a, "sms.send",
        {"to": "+15551234567", "body": "Your tech is on the way"},
    )

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1
    assert sms_calls == [("+15551234567", "Your tech is on the way")]
    assert email_calls == []

    row = service_db.execute(
        text("SELECT status FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dispatched"


def test_dispatch_dead_letters_an_sms_event_with_no_recipient(
    app_db, service_db, company_a
):
    _enqueue_and_commit(app_db, company_a, "sms.send", {"to": "", "body": "x"})

    for _ in range(outbox.MAX_DISPATCH_ATTEMPTS):
        outbox.dispatch_pending(service_db)

    row = service_db.execute(
        text("SELECT status, attempts FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dead_letter"
    assert row.attempts == outbox.MAX_DISPATCH_ATTEMPTS


def test_dispatch_moves_permanently_failing_sms_rows_to_dead_letter(
    monkeypatch, app_db, service_db, company_a
):
    monkeypatch.setattr(sms, "send_sms", lambda *a, **kw: False)

    _enqueue_and_commit(
        app_db, company_a, "sms.send", {"to": "+15551234567", "body": "x"}
    )

    for _ in range(outbox.MAX_DISPATCH_ATTEMPTS):
        outbox.dispatch_pending(service_db)

    row = service_db.execute(
        text("SELECT status, attempts FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dead_letter"
