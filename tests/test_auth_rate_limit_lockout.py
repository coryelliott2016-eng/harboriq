"""Login rate limiting and per-account lockout (migration 0005).

Two independent controls, tested independently:

  * A per-IP fixed-window rate limit (`app/core/rate_limit.py`) in front of
    both `/auth/login` and `/auth/password-reset/request` — a cheap speed
    bump, explicitly documented as in-process/non-distributed.
  * A per-account lockout (`failed_login_attempts`/`locked_until` columns,
    enforced inside `app/services/auth.py::login`) that survives a client
    switching IPs, which the rate limiter alone cannot do.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from tests.conftest import DEFAULT_PASSWORD, login, signup, unique_email


def test_exceeding_the_per_ip_limit_returns_429_with_retry_after(client):
    email = unique_email()
    signup(client, email=email)

    limit = settings.rate_limit_requests_per_window
    # The signup above already consumed a slot on the *login* limiter? No —
    # signup hits /auth/signup, a separate route with no rate limit, so the
    # login limiter's bucket for this test client's IP starts empty here.
    last_status = None
    for _ in range(limit):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": DEFAULT_PASSWORD},
        )
        last_status = resp.status_code
    assert last_status == 200

    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers


def test_password_reset_request_has_its_own_independent_limit(client):
    """Exhausting the login limiter must not throttle password-reset requests."""
    email = unique_email()
    signup(client, email=email)

    limit = settings.rate_limit_requests_per_window
    for _ in range(limit + 2):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "definitely-wrong-password"},
        )

    resp = client.post(
        "/api/v1/auth/password-reset/request", json={"email": email}
    )
    assert resp.status_code == 202, resp.text


def test_five_failed_logins_lock_the_account(client):
    email = unique_email()
    signup(client, email=email)

    max_attempts = settings.login_max_failed_attempts
    for _ in range(max_attempts - 1):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "definitely-wrong-password"},
        )
        assert resp.status_code == 401, resp.text

    # The Nth (final) wrong attempt trips the lock.
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "definitely-wrong-password"},
    )
    assert resp.status_code == 401, resp.text

    # The very next attempt is locked out — even with the CORRECT password,
    # and the response gives no hint that the account exists or is locked
    # for a credentials reason rather than any other.
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 423, resp.text
    body = resp.json()["detail"].lower()
    # The message may generically say "too many attempts", but must not leak
    # a specific count, the account's existence, or its email address.
    assert not any(char.isdigit() for char in body)
    assert email not in body


def test_lock_clears_once_locked_until_has_passed(client, service_db):
    email = unique_email()
    signup(client, email=email)

    max_attempts = settings.login_max_failed_attempts
    for _ in range(max_attempts):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "definitely-wrong-password"},
        )

    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 423, resp.text

    # Fast-forward the lock into the past directly in the DB — this is the
    # same trick the spec calls out for testing lock-expiry without sleeping
    # for real minutes.
    service_db.execute(
        text(
            "UPDATE users SET locked_until = :past WHERE email = :email"
        ),
        {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "email": email},
    )
    service_db.commit()

    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text("SELECT failed_login_attempts, locked_until FROM users WHERE email = :e"),
        {"e": email},
    ).first()
    assert row.failed_login_attempts == 0
    assert row.locked_until is None


def test_a_successful_login_resets_the_failed_attempt_counter(client, service_db):
    email = unique_email()
    signup(client, email=email)

    for _ in range(2):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "definitely-wrong-password"},
        )

    row = service_db.execute(
        text("SELECT failed_login_attempts FROM users WHERE email = :e"), {"e": email}
    ).first()
    assert row.failed_login_attempts == 2

    login(client, email)

    row = service_db.execute(
        text("SELECT failed_login_attempts, locked_until FROM users WHERE email = :e"),
        {"e": email},
    ).first()
    assert row.failed_login_attempts == 0
    assert row.locked_until is None


def test_unknown_email_still_returns_generic_invalid_credentials(client):
    """The lockout machinery must not change the unknown-email response shape."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email(), "password": "whatever-password"},
    )
    assert resp.status_code == 401, resp.text
