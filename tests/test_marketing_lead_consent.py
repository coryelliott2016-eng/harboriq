"""Contact permission is required; marketing permission is independent."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text

from app.services.marketing_leads import CONSENT_VERSION
from app.services import marketing_leads as leads_service


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


@pytest.mark.parametrize("recent_duplicate", [False, True])
@pytest.mark.parametrize("marketing_consent", [False, True])
def test_latest_marketing_preference_applies_to_all_email_history(
    client, service_db, recent_duplicate, marketing_consent
):
    service_db.execute(
        text(
            """
            INSERT INTO marketing_leads (
                full_name, business_name, email, team_size, created_at,
                contact_consent_at, consent_version, marketing_consent, marketing_consent_at
            ) VALUES
                ('Unknown contact', 'Marine', 'CONSENT@example.com', 'solo',
                 now() - interval '4 days', NULL, NULL, true, now() - interval '4 days'),
                ('Known contact', 'Marine', 'consent@example.com', 'solo',
                 now() - interval '3 days', now() - interval '3 days', 'old-version',
                 true, now() - interval '3 days'),
                ('Other email', 'Marine', 'other@example.com', 'solo',
                 now() - interval '3 days', NULL, NULL, true, now() - interval '3 days')
            """
        )
    )
    if recent_duplicate:
        service_db.execute(
            text(
                """
                INSERT INTO marketing_leads (
                    full_name, business_name, email, team_size, created_at
                ) VALUES ('Recent', 'Marine', 'consent@example.com', 'solo',
                          now() - interval '1 hour')
                """
            )
        )
    original = {
        row["id"]: dict(row)
        for row in service_db.execute(text("SELECT * FROM marketing_leads")).mappings()
    }
    service_db.commit()
    with patch("app.services.marketing_leads.notify_new_lead", return_value=False) as notify:
        response = client.post(
            "/api/v1/public/leads", json=_payload(marketing_consent=marketing_consent)
        )
    assert response.status_code == 201, response.text
    assert response.json()["duplicate"] is recent_duplicate
    assert notify.call_count == (0 if recent_duplicate else 1)
    updated = service_db.execute(text("SELECT * FROM marketing_leads")).mappings().all()
    selected = next(row for row in updated if str(row["id"]) == response.json()["id"])
    assert selected["contact_consent_at"] is not None
    assert selected["consent_version"] == CONSENT_VERSION
    for row in updated:
        previous = original.get(row["id"])
        if str(row["email"]).lower() == "consent@example.com":
            assert row["marketing_consent"] is marketing_consent
            assert row["marketing_consent_at"] == (
                selected["contact_consent_at"] if marketing_consent else None
            )
            if row["id"] != selected["id"]:
                assert row["contact_consent_at"] == previous["contact_consent_at"]
                assert row["consent_version"] == previous["consent_version"]
        else:
            assert dict(row) == previous
    assert len(updated) == len(original) + (0 if recent_duplicate else 1)


@pytest.mark.parametrize("first_preference", [False, True])
def test_concurrent_opposing_submissions_are_serialized(
    client, service_db, first_preference
):
    service_db.execute(
        text(
            """
            INSERT INTO marketing_leads (
                full_name, business_name, email, team_size, created_at, marketing_consent
            ) VALUES
                ('Legacy', 'Marine', 'consent@example.com', 'solo',
                 now() - interval '3 days', true),
                ('Other', 'Marine', 'other@example.com', 'solo',
                 now() - interval '3 days', true)
            """
        )
    )
    unrelated = dict(service_db.execute(
        text("SELECT * FROM marketing_leads WHERE email = 'other@example.com'")
    ).mappings().one())
    service_db.commit()
    first_locked, second_attempted = Event(), Event()
    counter_lock = Lock()
    attempts = 0
    real_lock = leads_service.lock_email_preference

    def synchronized_lock(db, email):
        nonlocal attempts
        with counter_lock:
            attempts += 1
            attempt = attempts
        if attempt == 2:
            second_attempted.set()
        real_lock(db, email)
        if attempt == 1:
            first_locked.set()
            assert second_attempted.wait(timeout=10), "second request did not reach the lock"

    with patch(
        "app.services.marketing_leads.lock_email_preference",
        side_effect=synchronized_lock,
    ), patch(
        "app.services.marketing_leads.notify_new_lead", return_value=False
    ) as notify, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            client.post, "/api/v1/public/leads",
            json=_payload(marketing_consent=first_preference),
        )
        assert first_locked.wait(timeout=10), "first request did not acquire the lock"
        second = pool.submit(
            client.post, "/api/v1/public/leads",
            json=_payload(email="CONSENT@example.com", marketing_consent=not first_preference),
        )
        first_response, second_response = first.result(timeout=15), second.result(timeout=15)
    assert first_response.status_code == second_response.status_code == 201
    assert first_response.json()["duplicate"] is False
    assert second_response.json()["duplicate"] is True
    assert first_response.json()["id"] == second_response.json()["id"]
    notify.assert_called_once()
    matching = service_db.execute(
        text("SELECT * FROM marketing_leads WHERE email = 'consent@example.com'")
    ).mappings().all()
    assert len(matching) == 2
    assert all(row["marketing_consent"] is (not first_preference) for row in matching)
    assert len({row["marketing_consent_at"] for row in matching}) == 1
    legacy = next(row for row in matching if row["full_name"] == "Legacy")
    assert legacy["contact_consent_at"] is None
    assert legacy["consent_version"] is None
    assert dict(service_db.execute(
        text("SELECT * FROM marketing_leads WHERE email = 'other@example.com'")
    ).mappings().one()) == unrelated


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
