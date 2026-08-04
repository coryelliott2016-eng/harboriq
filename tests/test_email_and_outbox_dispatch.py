"""Real email transport (`app/services/email.py`) and outbox dispatch.

No real network calls: `smtplib.SMTP`/`SMTP_SSL` are monkeypatched. Two
transport branches are exercised (console-fallback when `smtp_host` is
empty, and real SMTP when it is set), plus `outbox.dispatch_pending`
producing the right recipient/subject/link for each known event type and
correctly aging a permanently-failing row into `dead_letter`.
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.services import email, outbox


# ---------------------------------------------------------------------------
# app/services/email.py
# ---------------------------------------------------------------------------
def test_console_fallback_when_smtp_host_is_unset(monkeypatch, caplog):
    monkeypatch.setattr(settings, "smtp_host", "")
    calls = []
    monkeypatch.setattr(
        email.smtplib, "SMTP", lambda *a, **kw: calls.append((a, kw)) or None
    )

    with caplog.at_level("INFO", logger="harboriq.email"):
        ok = email.send_email("someone@example.com", "Subject", "Body text")

    assert ok is True
    assert calls == []  # smtplib was never touched
    assert any("console-transport" in rec.message for rec in caplog.records)


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=10):
        self.host = host
        self.port = port
        self.sent = []
        self.started_tls = False
        self.logged_in = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent.append(message)


def test_real_smtp_send_when_smtp_host_is_configured(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    monkeypatch.setattr(settings, "smtp_username", "apikey")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(email.smtplib, "SMTP", _FakeSMTP)

    ok = email.send_email("someone@example.com", "Subject", "Body text")

    assert ok is True
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("apikey", "secret")
    assert len(smtp.sent) == 1
    assert smtp.sent[0]["To"] == "someone@example.com"


def test_smtp_failure_is_caught_and_returns_false(monkeypatch):
    import smtplib

    def _boom(*a, **kw):
        raise smtplib.SMTPConnectError(421, "nope")

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(email.smtplib, "SMTP", _boom)

    ok = email.send_email("someone@example.com", "Subject", "Body text")
    assert ok is False


# ---------------------------------------------------------------------------
# app/services/outbox.py dispatch_pending
# ---------------------------------------------------------------------------
def _enqueue_and_commit(app_db, company_id, event_type, payload):
    from app.db.tenant import tenant_context

    with tenant_context(app_db, company_id):
        outbox.enqueue(app_db, company_id, event_type, payload)
        app_db.commit()


def test_dispatch_sends_password_reset_email_with_working_link(
    monkeypatch, app_db, service_db, company_a
):
    monkeypatch.setattr(settings, "smtp_host", "")  # console transport, deterministic
    sent = []
    monkeypatch.setattr(
        email, "send_email", lambda to, subject, body, html_body=None, attachments=None: (
            sent.append((to, subject, body)) or True
        )
    )

    _enqueue_and_commit(
        app_db,
        company_a,
        "auth.password_reset_requested",
        {"email": "owner@example.com", "reset_token": "raw-token-123", "expires_at": "x"},
    )

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "owner@example.com"
    assert "reset" in subject.lower()
    assert f"{settings.app_base_url.rstrip('/')}/reset-password/raw-token-123" in body

    row = service_db.execute(
        text("SELECT status FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dispatched"


def test_dispatch_sends_invite_email_with_accept_link(
    monkeypatch, app_db, service_db, company_a
):
    sent = []
    monkeypatch.setattr(
        email, "send_email", lambda to, subject, body, html_body=None, attachments=None: (
            sent.append((to, subject, body)) or True
        )
    )

    _enqueue_and_commit(
        app_db,
        company_a,
        "user_invite.sent",
        {
            "email": "newhire@example.com",
            "role": "technician",
            "full_name": None,
            "company_name": "Acme Marine",
            "inviter_name": "Jane Owner",
            "invite_token": "invite-raw-token",
            "ttl_hours": 168,
        },
    )

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1
    to, subject, body = sent[0]
    assert to == "newhire@example.com"
    assert "Acme Marine" in subject
    assert f"{settings.app_base_url.rstrip('/')}/accept-invite/invite-raw-token" in body


def test_dispatch_sends_invoice_email_using_the_provided_pay_url(
    monkeypatch, app_db, service_db, company_a
):
    sent = []
    monkeypatch.setattr(
        email, "send_email", lambda to, subject, body, html_body=None, attachments=None: (
            sent.append((to, subject, body, attachments)) or True
        )
    )

    _enqueue_and_commit(
        app_db,
        company_a,
        "invoice.send",
        {
            "invoice_id": "11111111-1111-1111-1111-111111111111",
            "customer_email": "customer@example.com",
            "pay_url": "/api/v1/public/invoice/some-raw-token",
        },
    )

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1
    to, subject, body, attachments = sent[0]
    assert to == "customer@example.com"
    assert "/api/v1/public/invoice/some-raw-token" in body
    # PDF generation is best-effort: an invoice id that does not resolve to a
    # real row (as here, a bare fixture payload with no DB-backed invoice)
    # must not fail the whole send -- it degrades to "no attachment" rather
    # than dead-lettering the email. Real PDF-attached delivery is covered by
    # tests/test_invoice_pdf_email.py against an actual invoice row.
    assert attachments in (None, [])


def test_dispatch_moves_permanently_failing_rows_to_dead_letter(
    monkeypatch, app_db, service_db, company_a
):
    monkeypatch.setattr(email, "send_email", lambda *a, **kw: False)

    _enqueue_and_commit(
        app_db,
        company_a,
        "auth.password_reset_requested",
        {"email": "x@example.com", "reset_token": "t", "expires_at": "x"},
    )

    for _ in range(outbox.MAX_DISPATCH_ATTEMPTS):
        outbox.dispatch_pending(service_db)

    row = service_db.execute(
        text("SELECT status, attempts FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dead_letter"
    assert row.attempts == outbox.MAX_DISPATCH_ATTEMPTS


def test_dispatch_is_a_noop_success_for_unhandled_event_types(
    app_db, service_db, company_a
):
    """`invoice.paid` (from stripe_webhooks) has no email template yet — must
    not spin forever waiting on a transport it will never use."""
    _enqueue_and_commit(app_db, company_a, "invoice.paid", {"invoice_id": "x"})

    dispatched = outbox.dispatch_pending(service_db)
    assert dispatched == 1

    row = service_db.execute(
        text("SELECT status FROM outbox_events WHERE company_id = :cid"),
        {"cid": company_a},
    ).first()
    assert row.status == "dispatched"
