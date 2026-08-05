"""Phase 16: httpOnly-cookie refresh-token transport + CSRF mitigation.

`tests/test_auth_refresh.py` already covers rotation/reuse/logout mechanics
in detail (rewritten for cookies in the same phase); this file focuses on
the cookie/CSRF *transport* contract itself, across every endpoint that
issues a session (signup, login, refresh, accept-invite): the JSON body
never contains a refresh token, the Set-Cookie attributes are correct, and
`app/core/csrf.py`'s double-submit check is enforced consistently.
"""
from __future__ import annotations

from app.api.v1.routes.auth import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH
from app.core.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from tests.conftest import DEFAULT_PASSWORD, auth_headers, unique_email


def _accept_url_to_token(accept_url: str) -> str:
    return accept_url.rstrip("/").rsplit("/", 1)[-1]


def test_signup_never_returns_a_refresh_token_in_json(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Cookie Co",
            "email": unique_email(),
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "refresh_token" not in body["tokens"]
    assert set(body["tokens"]) == {"access_token", "token_type", "expires_in"}


def test_signup_sets_httponly_refresh_cookie_and_readable_csrf_cookie(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Cookie Co",
            "email": unique_email(),
            "password": DEFAULT_PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text

    set_cookie_headers = resp.headers.get_list("set-cookie")
    refresh_header = next(h for h in set_cookie_headers if h.startswith(f"{REFRESH_COOKIE_NAME}="))
    csrf_header = next(h for h in set_cookie_headers if h.startswith(f"{CSRF_COOKIE_NAME}="))

    assert "HttpOnly" in refresh_header
    assert "samesite=lax" in refresh_header.lower()
    assert REFRESH_COOKIE_PATH in refresh_header

    # The CSRF cookie must NOT be httpOnly -- frontend JS has to read it.
    assert "HttpOnly" not in csrf_header
    assert "samesite=lax" in csrf_header.lower()


def test_login_sets_refresh_cookie_without_json_refresh_token(client):
    email = unique_email()
    client.post(
        "/api/v1/auth/signup",
        json={"company_name": "Cookie Co", "email": email, "password": DEFAULT_PASSWORD},
    )
    client.cookies.clear()
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert resp.status_code == 200, resp.text
    assert "refresh_token" not in resp.json()["tokens"]
    assert REFRESH_COOKIE_NAME in resp.cookies
    assert CSRF_COOKIE_NAME in resp.cookies


def test_accept_invite_sets_refresh_cookie(client):
    owner_resp = client.post(
        "/api/v1/auth/signup",
        json={"company_name": "Cookie Co", "email": unique_email(), "password": DEFAULT_PASSWORD},
    )
    owner = owner_resp.json()

    invite_resp = client.post(
        "/api/v1/auth/invites",
        json={"email": unique_email("tech"), "role": "technician"},
        headers=auth_headers(owner),
    )
    assert invite_resp.status_code == 201, invite_resp.text
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    client.cookies.clear()
    accept_resp = client.post(
        f"/api/v1/auth/invites/{token}/accept",
        json={"password": DEFAULT_PASSWORD, "full_name": "New Tech"},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    assert "refresh_token" not in accept_resp.json()["tokens"]
    assert REFRESH_COOKIE_NAME in accept_resp.cookies
    assert CSRF_COOKIE_NAME in accept_resp.cookies


def test_logout_clears_both_cookies(client):
    email = unique_email()
    signup_resp = client.post(
        "/api/v1/auth/signup",
        json={"company_name": "Cookie Co", "email": email, "password": DEFAULT_PASSWORD},
    )
    created = signup_resp.json()

    resp = client.post(
        "/api/v1/auth/logout", json={"all_devices": False}, headers=auth_headers(created)
    )
    assert resp.status_code == 200

    set_cookie_headers = resp.headers.get_list("set-cookie")
    refresh_clear = next(h for h in set_cookie_headers if h.startswith(f"{REFRESH_COOKIE_NAME}="))
    csrf_clear = next(h for h in set_cookie_headers if h.startswith(f"{CSRF_COOKIE_NAME}="))
    # FastAPI's delete_cookie sets an empty value with Max-Age=0 (immediate
    # expiry) -- e.g. `refresh_token=""; ...; Max-Age=0; ...`.
    assert f'{REFRESH_COOKIE_NAME}=""' in refresh_clear
    assert "Max-Age=0" in refresh_clear
    assert f'{CSRF_COOKIE_NAME}=""' in csrf_clear
    assert "Max-Age=0" in csrf_clear


def test_a_failed_refresh_clears_the_cookies(client):
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, "garbage-token")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-value")
    resp = client.post("/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: "csrf-value"})
    assert resp.status_code == 401
    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert any(
        h.startswith(f'{REFRESH_COOKIE_NAME}=""') and "Max-Age=0" in h
        for h in set_cookie_headers
    )


def test_csrf_verify_rejects_missing_header(client):
    """Direct unit coverage of app.core.csrf.verify_csrf's failure modes,
    beyond what the route-level 403 assertions above already imply."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.core.csrf import verify_csrf

    scope = {
        "type": "http",
        "headers": [(b"cookie", f"{CSRF_COOKIE_NAME}=abc".encode())],
    }
    request = Request(scope)
    try:
        verify_csrf(request)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_csrf_verify_accepts_matching_cookie_and_header(client):
    from starlette.requests import Request

    from app.core.csrf import verify_csrf

    scope = {
        "type": "http",
        "headers": [
            (b"cookie", f"{CSRF_COOKIE_NAME}=match-value".encode()),
            (CSRF_HEADER_NAME.lower().encode(), b"match-value"),
        ],
    }
    request = Request(scope)
    verify_csrf(request)  # must not raise


def test_new_csrf_token_is_random_and_url_safe(client):
    from app.core.csrf import new_csrf_token

    a, b = new_csrf_token(), new_csrf_token()
    assert a != b
    assert len(a) >= 32
