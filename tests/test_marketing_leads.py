"""Public marketing lead capture (GTM / trial signup)."""
from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
import pytest


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


@pytest.mark.parametrize("changed", [
    {"industry": "surveyors"}, {"product_interest": "partnership"},
    {"business_need": "Human-reviewed survey workflows"},
    {"email_marketing_opt_in": True}, {"contact_requested": False},
])
def test_changed_classification_or_permission_is_not_dropped(client, service_db, changed):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=True):
        first = client.post("/api/v1/public/leads", json=_payload())
        second = client.post("/api/v1/public/leads", json=_payload(**changed))
    assert first.status_code == second.status_code == 201
    assert second.json()["duplicate"] is False
    assert second.json()["id"] != first.json()["id"]
    assert service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar() == 2


def test_consent_and_classification_in_admin_list(client, service_db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "marketing_leads_admin_token", "test-admin-token")
    with patch("app.services.marketing_leads.email_service.send_email", return_value=True) as send:
        response = client.post("/api/v1/public/leads", json=_payload(
            industry="commercial-fishing", product_interest="ai", business_need="Office planning",
            email_marketing_opt_in=True, contact_requested=False,
        ))
    assert response.status_code == 201
    assert "follow up" not in response.json()["message"]
    send.assert_called_once()
    assert "Internal routing only" in send.call_args.kwargs["text_body"]
    assert "No permission to contact" in send.call_args.kwargs["text_body"]
    assert send.call_args.kwargs["to"] == settings.marketing_lead_notify_to
    listing = client.get(
        "/api/v1/public/leads", headers={"Authorization": "Bearer " + "test-admin-token"},
    )
    assert listing.status_code == 200
    lead = listing.json()["leads"][0]
    assert lead["classification"] == "commercial-fishing:ai"
    assert lead["business_need"] == "Office planning"
    assert lead["email_marketing_opt_in"] is True
    assert lead["contact_requested"] is False
    assert lead["email_marketing_consented_at"]
    assert lead["email_marketing_consent_version"]


def test_default_consent_remains_null(client, service_db):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=False):
        assert client.post("/api/v1/public/leads", json=_payload()).status_code == 201
    row = service_db.execute(text("SELECT * FROM marketing_leads")).mappings().one()
    assert row["industry"] == "other"
    assert row["contact_requested"] is True
    assert row["email_marketing_opt_in"] is False
    assert row["email_marketing_consented_at"] is None
    assert row["email_marketing_consent_version"] is None


def test_changing_permission_back_is_not_deduplicated_to_older_row(client, service_db):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=False):
        first = client.post("/api/v1/public/leads", json=_payload())
        second = client.post("/api/v1/public/leads", json=_payload(email_marketing_opt_in=True))
        third = client.post("/api/v1/public/leads", json=_payload())
    assert first.status_code == second.status_code == third.status_code == 201
    assert third.json()["duplicate"] is False
    assert len({first.json()["id"], second.json()["id"], third.json()["id"]}) == 3
    assert service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar() == 3


def test_contact_false_never_promises_followup_even_for_duplicate_or_honeypot(client):
    with patch("app.services.marketing_leads.email_service.send_email", return_value=False):
        responses = [
            client.post("/api/v1/public/leads", json=_payload(contact_requested=False)),
            client.post("/api/v1/public/leads", json=_payload(contact_requested=False)),
            client.post("/api/v1/public/leads", json=_payload(
                contact_requested=False, website="bot.example",
            )),
        ]
    for response in responses:
        assert response.status_code == 201
        assert "follow up" not in response.json()["message"].lower()
        assert "contact" not in response.json()["message"].lower()
    assert responses[1].json()["duplicate"] is True


def test_migration_existing_lead_defaults_do_not_infer_marketing(service_db, monkeypatch):
    # A transaction-local shadow table exercises the real migration without altering
    # the shared schema or requiring a destructive downgrade of the test database.
    service_db.execute(text("""
        CREATE TEMPORARY TABLE marketing_leads (email TEXT NOT NULL) ON COMMIT DROP
    """))
    service_db.execute(text("INSERT INTO marketing_leads (email) VALUES ('legacy@example.com')"))
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0026_marketing_lead_industry_consent.py"
    migration = runpy.run_path(str(path))
    monkeypatch.setattr(migration["op"], "execute", lambda sql: service_db.execute(text(sql)))
    migration["upgrade"]()
    row = service_db.execute(text("SELECT * FROM marketing_leads")).mappings().one()
    assert row["email"] == "legacy@example.com"
    assert row["industry"] == "other"
    assert row["product_interest"] == "operations"
    assert row["business_need"] == ""
    assert row["contact_requested"] is True
    assert row["email_marketing_opt_in"] is False
    assert row["email_marketing_consented_at"] is None
    assert row["email_marketing_consent_version"] is None
    migration["downgrade"]()
    assert service_db.execute(text("SELECT email FROM marketing_leads")).scalar_one() == "legacy@example.com"


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
