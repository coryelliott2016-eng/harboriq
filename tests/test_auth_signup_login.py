"""Signup, login and current-user behaviour, end to end over HTTP."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.conftest import DEFAULT_PASSWORD, auth_headers, signup, unique_email


def test_signup_creates_tenant_and_owner(client, service_db):
    email = unique_email()
    body = signup(client, company_name="Acme Marine", email=email, full_name="Ada Owner")

    assert body["user"]["email"] == email
    assert body["user"]["role"] == "owner"
    assert body["user"]["is_active"] is True
    assert body["tokens"]["token_type"] == "bearer"
    assert body["tokens"]["expires_in"] == settings.access_token_ttl_minutes * 60
    assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]

    company_id = body["user"]["company_id"]
    row = service_db.execute(
        text("SELECT slug, name FROM companies WHERE id = :cid"), {"cid": company_id}
    ).one()
    assert row.name == "Acme Marine"
    assert row.slug == "acme-marine"


def test_signup_slug_collision_gets_a_distinct_slug(client, service_db):
    first = signup(client, company_name="Acme Marine")
    second = signup(client, company_name="Acme Marine")

    slugs = service_db.execute(
        text("SELECT slug FROM companies WHERE id = ANY(:ids)"),
        {"ids": [first["user"]["company_id"], second["user"]["company_id"]]},
    ).scalars().all()
    assert len(set(slugs)) == 2


def test_signup_rejects_an_explicitly_taken_slug(client):
    signup(client, company_name="Acme Marine", company_slug="harbor-one")
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Other Marine",
            "company_slug": "harbor-one",
            "email": unique_email(),
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 409


def test_signup_rejects_a_duplicate_email_across_tenants(client):
    """One email identifies exactly one account platform-wide (login needs this)."""
    email = unique_email()
    signup(client, email=email)

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Bayside Yachts",
            "email": email,
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 409


def test_signup_email_match_is_case_insensitive(client):
    email = unique_email()
    signup(client, email=email)

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Bayside Yachts",
            "email": email.upper(),
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 409


@pytest.mark.parametrize("password", ["short", "abcdefghijk"])
def test_signup_rejects_a_weak_password(client, password):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Acme Marine",
            "email": unique_email(),
            "password": password,
        },
    )
    assert resp.status_code == 422


def test_login_succeeds_and_issues_a_fresh_session(client, service_db):
    email = unique_email()
    created = signup(client, email=email)

    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == created["user"]["id"]
    assert body["tokens"]["refresh_token"] != created["tokens"]["refresh_token"]

    sessions = service_db.execute(
        text("SELECT count(*) FROM user_sessions WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalar_one()
    assert sessions == 2


def test_login_is_case_insensitive_on_email(client):
    email = unique_email()
    signup(client, email=email)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email.upper(), "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200


def test_login_rejects_a_wrong_password(client):
    email = unique_email()
    signup(client, email=email)
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password-here"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid email or password"


def test_login_rejects_an_unknown_email_with_the_same_error(client):
    """Identical response for unknown email and wrong password (no enumeration)."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email("nobody"), "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid email or password"


def test_login_rejects_a_deactivated_user(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    service_db.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.commit()

    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 401


def test_me_returns_the_authenticated_user(client):
    created = signup(client)
    resp = client.get("/api/v1/auth/me", headers=auth_headers(created))
    assert resp.status_code == 200
    assert resp.json() == created["user"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ],
)
def test_me_requires_a_valid_bearer_token(client, headers):
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


def test_me_rejects_an_expired_access_token(client, monkeypatch):
    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
    created = signup(client)
    monkeypatch.undo()

    resp = client.get("/api/v1/auth/me", headers=auth_headers(created))
    assert resp.status_code == 401


def test_me_rejects_a_token_signed_with_another_key(client, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "an-entirely-different-signing-key-32b")
    created = signup(client)
    monkeypatch.undo()

    resp = client.get("/api/v1/auth/me", headers=auth_headers(created))
    assert resp.status_code == 401


def test_me_rejects_a_user_deactivated_after_the_token_was_issued(client, service_db):
    created = signup(client)
    service_db.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.commit()

    resp = client.get("/api/v1/auth/me", headers=auth_headers(created))
    assert resp.status_code == 401


def test_password_is_never_stored_in_plaintext(client, service_db):
    email = unique_email()
    created = signup(client, email=email)
    stored = service_db.execute(
        text("SELECT password_hash FROM users WHERE id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalar_one()
    assert DEFAULT_PASSWORD not in stored
    assert stored.startswith("$argon2")
