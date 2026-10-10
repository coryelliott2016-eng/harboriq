"""Contact permission is required; marketing permission is independent."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text

from app.services.marketing_leads import CONSENT_VERSION


def _payload(**overrides):
    return {
        "full_name": "Consent Test",
        "business_name": "Marine Test",
        "email": "consent@example.com",
        "contact_consent": True,
        **overrides,
    }


def _row(db):
    return db.execute(text("SELECT * FROM marketing_leads")).mappings().one()


def test_migration_does_not_backfill_legacy_permission(service_db):
    # A session-local table exercises the real migration without changing shared schema.
    service_db.execute(
        text(
            """
            CREATE TEMP TABLE marketing_leads (
                full_name TEXT, business_name TEXT, email TEXT, team_size TEXT
            ) ON COMMIT DROP
            """
        )
    )
    service_db.execute(
        text(
            """
            INSERT INTO marketing_leads VALUES
                ('Legacy', 'Legacy Marine', 'legacy@example.com', 'solo')
            """
        )
    )
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "sql" / "0026_marketing_lead_consent.sql"
    )
    service_db.execute(text(migration.read_text()))
    row = _row(service_db)
    assert row["contact_consent_at"] is None
    assert row["consent_version"] is None
    assert row["marketing_consent"] is False
    assert row["marketing_consent_at"] is None
    service_db.rollback()


@pytest.mark.no_db
@pytest.mark.parametrize("value", [None, False, 1, "true"])
def test_contact_consent_must_be_explicit_true(client, value):
    payload = _payload(contact_consent=value)
    if value is None:
        payload.pop("contact_consent")
    response = client.post("/api/v1/public/leads", json=payload)
    assert response.status_code == 422


def test_contact_only_defaults_and_minimal_metadata(client, service_db):
    with patch("app.services.marketing_leads.notify_new_lead", return_value=False):
        response = client.post(
            "/api/v1/public/leads",
            json=_payload(
                consent_version="untrusted-client-version",
                analytics_consent=True,
                referral_consent=True,
            ),
            headers={"X-Forwarded-For": "192.0.2.1", "User-Agent": "test-browser"},
        )
    assert response.status_code == 201, response.text
    row = _row(service_db)
    assert row["contact_consent_at"] is not None
    assert row["consent_version"] == CONSENT_VERSION
    assert row["marketing_consent"] is False
    assert row["marketing_consent_at"] is None
    assert row["ip_hint"] is None
    assert row["user_agent"] is None
    assert set(response.json()) == {"ok", "id", "duplicate", "message"}


def test_duplicate_latest_preference_including_opt_out(client, service_db):
    with patch("app.services.marketing_leads.notify_new_lead", return_value=False) as notify:
        first = client.post("/api/v1/public/leads", json=_payload())
        initial_time = _row(service_db)["contact_consent_at"]
        service_db.commit()
        second = client.post(
            "/api/v1/public/leads", json=_payload(marketing_consent=True)
        )
        assert second.status_code == 201, second.text
        row = _row(service_db)
        assert row["marketing_consent"] is True
        assert row["marketing_consent_at"] is not None
        assert row["contact_consent_at"] >= initial_time
        service_db.commit()
        third = client.post(
            "/api/v1/public/leads", json=_payload(marketing_consent=False)
        )
        assert third.status_code == 201, third.text
        assert _row(service_db)["marketing_consent"] is False
        assert _row(service_db)["marketing_consent_at"] is None
        service_db.commit()
        client.post("/api/v1/public/leads", json=_payload(marketing_consent=True))
        # An unchecked checkbox is omitted by some callers: default false is an opt-out.
        fourth = client.post("/api/v1/public/leads", json=_payload())
    assert first.status_code == second.status_code == third.status_code == fourth.status_code == 201
    assert first.json()["id"] == second.json()["id"] == third.json()["id"]
    assert second.json()["duplicate"] is third.json()["duplicate"] is True
    assert _row(service_db)["marketing_consent"] is False
    assert _row(service_db)["marketing_consent_at"] is None
    assert _row(service_db)["consent_version"] == CONSENT_VERSION
    assert service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar() == 1
    notify.assert_called_once()


def test_legacy_contact_unknown_preserved_until_explicit_submission(client, service_db, monkeypatch):
    service_db.execute(
        text(
            """
            INSERT INTO marketing_leads (full_name, business_name, email, team_size)
            VALUES ('Legacy Lead', 'Legacy Marine', 'consent@example.com', 'solo')
            """
        )
    )
    service_db.commit()
    monkeypatch.setattr(
        "app.core.config.settings.marketing_leads_admin_token", "consent-admin-test"
    )
    assert client.get("/api/v1/public/leads").status_code == 401
    assert client.get(
        "/api/v1/public/leads", headers={"Authorization": "Bearer " + "wrong-consent-token"}
    ).status_code == 401
    admin = client.get(
        "/api/v1/public/leads", headers={"Authorization": "Bearer " + "consent-admin-test"}
    )
    assert admin.status_code == 200, admin.text
    legacy = admin.json()["leads"][0]
    assert legacy["contact_consent_at"] is None
    assert legacy["consent_version"] is None
    assert legacy["marketing_consent"] is False
    assert legacy["marketing_consent_at"] is None
    assert _row(service_db)["contact_consent_at"] is None
    service_db.commit()
    with patch("app.services.marketing_leads.notify_new_lead") as notify:
        response = client.post("/api/v1/public/leads", json=_payload())
    assert response.status_code == 201
    assert response.json()["duplicate"] is True
    assert _row(service_db)["contact_consent_at"] is not None
    assert _row(service_db)["consent_version"] == CONSENT_VERSION
    assert _row(service_db)["marketing_consent"] is False
    notify.assert_not_called()


def test_redis_unavailable_fails_closed_without_lead(client, service_db):
    with patch(
        "app.api.v1.routes.marketing_leads.get_redis",
        side_effect=RedisConnectionError("unavailable"),
    ), patch("app.services.marketing_leads.notify_new_lead") as notify:
        response = client.post("/api/v1/public/leads", json=_payload())
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "60"
    assert service_db.execute(text("SELECT count(*) FROM marketing_leads")).scalar() == 0
    notify.assert_not_called()


@pytest.mark.no_db
def test_redis_eval_failure_fails_closed(client):
    with patch("app.api.v1.routes.marketing_leads.get_redis") as redis:
        redis.return_value.eval.side_effect = RedisConnectionError("unavailable")
        response = client.post("/api/v1/public/leads", json=_payload())
    assert response.status_code == 503


def test_honeypot_never_changes_existing_consent(client, service_db):
    with patch("app.services.marketing_leads.notify_new_lead", return_value=False):
        client.post("/api/v1/public/leads", json=_payload(marketing_consent=True))
        original = dict(_row(service_db))
        service_db.commit()
        response = client.post(
            "/api/v1/public/leads", json=_payload(website="bot", marketing_consent=False)
        )
    assert response.status_code == 201
    assert _row(service_db)["marketing_consent"] is True
    assert _row(service_db)["contact_consent_at"] == original["contact_consent_at"]
