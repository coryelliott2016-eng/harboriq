"""Password reset: request, confirm, single-use and session revocation."""
from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from tests.conftest import DEFAULT_PASSWORD, signup, unique_email

NEW_PASSWORD = "a-brand-new-passphrase"


def _request_reset(client, email: str):
    return client.post("/api/v1/auth/password-reset/request", json={"email": email})


def _reset_token(service_db, company_id: str) -> str:
    """The raw token is delivered through the outbox, never the HTTP response."""
    payload = service_db.execute(
        text(
            """
            SELECT payload FROM outbox_events
             WHERE company_id = :cid AND event_type = 'auth.password_reset_requested'
             ORDER BY id DESC LIMIT 1
            """
        ),
        {"cid": company_id},
    ).scalar_one()
    return payload["reset_token"]


def test_request_enqueues_an_outbox_event_carrying_the_token(client, service_db):
    email = unique_email()
    created = signup(client, email=email)

    resp = _request_reset(client, email)
    assert resp.status_code == 202
    assert resp.content == b""

    token = _reset_token(service_db, created["user"]["company_id"])
    assert token

    stored = service_db.execute(
        text("SELECT token_hash FROM password_reset_tokens WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalar_one()
    assert stored != token
    assert len(stored) == 64


def test_request_for_an_unknown_email_still_returns_202(client, service_db):
    resp = _request_reset(client, unique_email("nobody"))
    assert resp.status_code == 202
    assert service_db.execute(
        text("SELECT count(*) FROM password_reset_tokens")
    ).scalar_one() == 0


def test_request_for_a_deactivated_user_issues_nothing(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    service_db.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.commit()

    assert _request_reset(client, email).status_code == 202
    assert service_db.execute(
        text("SELECT count(*) FROM password_reset_tokens")
    ).scalar_one() == 0


def test_confirm_sets_the_new_password_and_retires_the_old_one(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    _request_reset(client, email)
    token = _reset_token(service_db, created["user"]["company_id"])

    resp = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 204

    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}
    ).status_code == 200


def test_confirm_revokes_every_existing_session(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    other = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    ).json()

    _request_reset(client, email)
    token = _reset_token(service_db, created["user"]["company_id"])
    client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )

    for tokens in (created, other):
        assert client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["tokens"]["refresh_token"]},
        ).status_code == 401

    reasons = service_db.execute(
        text("SELECT DISTINCT revoked_reason FROM user_sessions WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalars().all()
    assert reasons == ["password_reset"]


def test_a_reset_token_is_single_use(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    _request_reset(client, email)
    token = _reset_token(service_db, created["user"]["company_id"])

    first = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert first.status_code == 204

    second = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "yet-another-passphrase"},
    )
    assert second.status_code == 400


def test_confirming_one_token_voids_the_other_outstanding_ones(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    _request_reset(client, email)
    first_token = _reset_token(service_db, created["user"]["company_id"])
    _request_reset(client, email)
    second_token = _reset_token(service_db, created["user"]["company_id"])
    assert first_token != second_token

    assert client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second_token, "new_password": NEW_PASSWORD},
    ).status_code == 204

    assert client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first_token, "new_password": "third-passphrase-here"},
    ).status_code == 400


def test_confirm_rejects_an_expired_token(client, service_db, monkeypatch):
    email = unique_email()
    created = signup(client, email=email)
    monkeypatch.setattr(settings, "password_reset_ttl_minutes", -1)
    _request_reset(client, email)
    monkeypatch.undo()

    token = _reset_token(service_db, created["user"]["company_id"])
    resp = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 400


def test_confirm_rejects_an_unknown_token(client):
    resp = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-reset-token", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 400


def test_confirm_rejects_a_weak_new_password_without_burning_the_token(
    client, service_db
):
    email = unique_email()
    created = signup(client, email=email)
    _request_reset(client, email)
    token = _reset_token(service_db, created["user"]["company_id"])

    assert client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "short"},
    ).status_code == 422

    # The token survived, so the user does not need a second email.
    assert client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    ).status_code == 204


def test_reset_tokens_are_isolated_across_tenants(client, app_db, service_db):
    a_email = unique_email()
    a = signup(client, email=a_email)
    b = signup(client)
    _request_reset(client, a_email)

    from app.db.tenant import tenant_context

    with tenant_context(app_db, b["user"]["company_id"]):
        assert app_db.execute(
            text("SELECT count(*) FROM password_reset_tokens")
        ).scalar_one() == 0
    with tenant_context(app_db, a["user"]["company_id"]):
        assert app_db.execute(
            text("SELECT count(*) FROM password_reset_tokens")
        ).scalar_one() == 1

