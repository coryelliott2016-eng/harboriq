"""Public marketing lead capture (GTM / trial signup)."""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text


def _payload(**overrides):
    base = {
        "full_name": "Cory Elliott",
        "business_name": "Off the Hook Marine",
        "email": "lead@example.com",
        "team_size": "solo",
        "source": "marketing-signup",
        "website": "",
    }
    base.update(overrides)
    return base


def test_create_lead_stores_row_and_notifies(client, service_db):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=True) as send:
        resp = client.post("/api/v1/public/leads", json=_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["duplicate"] is False
    assert "follow up" in body["message"].lower()
    send.assert_called_once()
    assert send.call_args.kwargs["to"]  # notify address configured

    row = service_db.execute(
        text("SELECT full_name, business_name, email, team_size, notified_at FROM marketing_leads")
    ).mappings().one()
    assert row["full_name"] == "Cory Elliott"
    assert row["business_name"] == "Off the Hook Marine"
    assert str(row["email"]).lower() == "lead@example.com"
    assert row["team_size"] == "solo"
    # BackgroundTasks run before TestClient returns; notified_at should be set.
    assert row["notified_at"] is not None


def test_honeypot_does_not_store(client, service_db):
    resp = client.post(
        "/api/v1/public/leads",
        json=_payload(website="http://spam.example"),
    )
    assert resp.status_code == 201
    assert resp.json()["ok"] is True
    count = service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar()
    assert count == 0


def test_duplicate_email_within_24h_no_second_notify(client, service_db):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=True) as send:
        first = client.post("/api/v1/public/leads", json=_payload())
        second = client.post("/api/v1/public/leads", json=_payload(full_name="Again"))
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    assert send.call_count == 1
    count = service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar()
    assert count == 1


def test_invalid_email_rejected(client):
    resp = client.post("/api/v1/public/leads", json=_payload(email="not-an-email"))
    assert resp.status_code == 422


def test_invalid_team_size_rejected(client):
    resp = client.post("/api/v1/public/leads", json=_payload(team_size="fleet"))
    assert resp.status_code == 422


def test_list_requires_admin_token(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.routes.marketing_leads.settings.marketing_leads_admin_token",
        "test-admin-token-xyz",
    )
    # Also patch settings object used at import time via module reference
    from app.core import config

    monkeypatch.setattr(config.settings, "marketing_leads_admin_token", "test-admin-token-xyz")

    denied = client.get("/api/v1/public/leads")
    assert denied.status_code == 401

    wrong = client.get(
        "/api/v1/public/leads",
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401

    with patch("app.services.marketing_leads.email_service.send_email", return_value=True):
        client.post("/api/v1/public/leads", json=_payload(email="listme@example.com"))

    ok = client.get(
        "/api/v1/public/leads",
        headers={"Authorization": "Bearer test-admin-token-xyz"},
    )
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["count"] >= 1
    assert any(lead["email"] == "listme@example.com" for lead in data["leads"])


def test_list_disabled_when_token_empty(client, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "marketing_leads_admin_token", "")
    monkeypatch.setattr(
        "app.api.v1.routes.marketing_leads.settings.marketing_leads_admin_token",
        "",
    )
    resp = client.get(
        "/api/v1/public/leads",
        headers={"Authorization": "Bearer anything"},
    )
    assert resp.status_code == 401


def test_rate_limit_returns_429(client, monkeypatch):
    from app.core import config
    from app.core.rate_limit import _reset_all_for_tests

    monkeypatch.setattr(config.settings, "marketing_lead_rate_limit_per_window", 2)
    # Rebuild limiter thresholds by hitting the module-level limiter directly
    from app.core import rate_limit as rl

    rl._marketing_lead_limiter.limit = 2
    _reset_all_for_tests()

    with patch("app.services.marketing_leads.email_service.send_email", return_value=True):
        assert client.post("/api/v1/public/leads", json=_payload(email="a@example.com")).status_code == 201
        assert client.post("/api/v1/public/leads", json=_payload(email="b@example.com")).status_code == 201
        third = client.post("/api/v1/public/leads", json=_payload(email="c@example.com"))
    assert third.status_code == 429
    assert "Retry-After" in third.headers

    # restore default for other tests
    rl._marketing_lead_limiter.limit = config.settings.marketing_lead_rate_limit_per_window
    _reset_all_for_tests()
