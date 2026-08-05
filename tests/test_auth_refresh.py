"""Refresh-token rotation, reuse detection and logout.

Phase 16: the refresh token travels as an httpOnly cookie, never in the
JSON body/response (see app/api/v1/routes/auth.py). Since the shared
`client` fixture uses one TestClient with one shared cookie jar, tests that
need two independent "devices" alive at once (logout-only-this-device,
reuse-detection, concurrent rotation) extract each response's own
Set-Cookie values and pass them explicitly on subsequent calls via the
`cookies=` kwarg instead of relying on the jar, which would just clobber the
earlier session's cookie with the newer one.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.routes.auth import REFRESH_COOKIE_NAME
from app.core.config import settings
from app.core.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.services.auth import InvalidRefreshToken
from app.services.auth import refresh as refresh_service
from tests.conftest import auth_headers


def _session_cookies(resp) -> dict[str, str]:
    """Extract the (refresh, csrf) cookie pair this response just set."""
    return {
        REFRESH_COOKIE_NAME: resp.cookies[REFRESH_COOKIE_NAME],
        CSRF_COOKIE_NAME: resp.cookies[CSRF_COOKIE_NAME],
    }


def _refresh(client, cookies: dict[str, str]):
    """POST /auth/refresh using an explicit cookie pair (not the shared jar).

    Overwrites the client's own jar directly (rather than the deprecated
    per-request `cookies=` kwarg some httpx/starlette combinations warn
    about) so a *different* session's cookie left over from an earlier call
    against the same shared `client` fixture can never silently win.
    """
    client.cookies.clear()
    for key, value in cookies.items():
        client.cookies.set(key, value)
    return client.post(
        "/api/v1/auth/refresh",
        headers={CSRF_HEADER_NAME: cookies[CSRF_COOKIE_NAME]},
    )


def _signup_session(client, **kw) -> tuple[dict, dict[str, str]]:
    """Sign up and return (AuthResponse body, its cookie pair)."""
    client.cookies.clear()
    body = {
        "company_name": kw.pop("company_name", "Acme Marine"),
        "email": kw.pop("email", None),
        "password": kw.pop("password", "correct-horse-battery-staple"),
        **kw,
    }
    if body["email"] is None:
        import uuid

        body["email"] = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json(), _session_cookies(resp)


def _login_session(client, email: str, password: str = "correct-horse-battery-staple"):
    client.cookies.clear()
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json(), _session_cookies(resp)


def test_refresh_sets_a_new_httponly_cookie_and_rotates_csrf(client):
    created, cookies = _signup_session(client)
    resp = _refresh(client, cookies)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["user"]["id"] == created["user"]["id"]
    # The JSON body no longer carries a refresh_token at all.
    assert "refresh_token" not in body["tokens"]
    # A fresh cookie pair was issued and differs from the one presented.
    new_refresh = resp.cookies[REFRESH_COOKIE_NAME]
    assert new_refresh != cookies[REFRESH_COOKIE_NAME]
    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert any(REFRESH_COOKIE_NAME in h and "HttpOnly" in h for h in set_cookie_headers)
    assert any(CSRF_COOKIE_NAME in h and "HttpOnly" not in h for h in set_cookie_headers)
    # The new access token works.
    assert client.get("/api/v1/auth/me", headers=auth_headers(body)).status_code == 200


def test_refresh_requires_a_matching_csrf_header(client):
    _created, cookies = _signup_session(client)
    client.cookies.clear()
    for key, value in cookies.items():
        client.cookies.set(key, value)
    # Cookie present, but the CSRF header is missing entirely.
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 403


def test_refresh_rejects_a_mismatched_csrf_header(client):
    _created, cookies = _signup_session(client)
    client.cookies.clear()
    for key, value in cookies.items():
        client.cookies.set(key, value)
    resp = client.post(
        "/api/v1/auth/refresh",
        headers={CSRF_HEADER_NAME: "not-the-right-token"},
    )
    assert resp.status_code == 403


def test_refresh_without_a_cookie_is_unauthorized(client):
    client.cookies.clear()
    resp = client.post(
        "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: "whatever"}
    )
    # No refresh cookie and no csrf cookie -> CSRF check fires first (403).
    assert resp.status_code == 403


def test_refresh_with_cookie_but_no_csrf_cookie_is_forbidden(client):
    """A refresh cookie alone (CSRF cookie missing) must not be enough."""
    _created, cookies = _signup_session(client)
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, cookies[REFRESH_COOKIE_NAME])
    resp = client.post(
        "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: "whatever"}
    )
    assert resp.status_code == 403


def test_rotation_invalidates_the_presented_token(client):
    created, cookies = _signup_session(client)
    assert _refresh(client, cookies).status_code == 200

    replay = _refresh(client, cookies)
    assert replay.status_code == 401
    assert replay.headers["WWW-Authenticate"] == "Bearer"


def test_reuse_revokes_the_whole_family(client, service_db):
    """Replaying a rotated token means it leaked — kill every descendant."""
    created, cookies = _signup_session(client)
    first_resp = _refresh(client, cookies)
    rotated_cookies = _session_cookies(first_resp)

    # Attacker replays the already-used token.
    assert _refresh(client, cookies).status_code == 401

    # The legitimate holder's current token is now dead too.
    assert _refresh(client, rotated_cookies).status_code == 401

    reasons = service_db.execute(
        text(
            "SELECT DISTINCT revoked_reason FROM user_sessions WHERE user_id = :uid"
        ),
        {"uid": created["user"]["id"]},
    ).scalars().all()
    assert reasons == ["reuse_detected"]


def test_reuse_detection_is_audited(client, service_db):
    created, cookies = _signup_session(client)
    _refresh(client, cookies)
    _refresh(client, cookies)

    actions = service_db.execute(
        text("SELECT action FROM audit_log WHERE company_id = :cid"),
        {"cid": created["user"]["company_id"]},
    ).scalars().all()
    assert "auth.refresh_reuse_detected" in actions


def test_refresh_rejects_an_unknown_token(client):
    resp = _refresh(
        client,
        {
            REFRESH_COOKIE_NAME: "definitely-not-a-real-refresh-token",
            CSRF_COOKIE_NAME: "csrf",
        },
    )
    assert resp.status_code == 401


def test_refresh_rejects_an_expired_session(client, service_db):
    created, cookies = _signup_session(client)
    service_db.execute(
        text("UPDATE user_sessions SET expires_at = now() - interval '1 day' "
             "WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.commit()

    assert _refresh(client, cookies).status_code == 401


def test_refresh_rejects_an_access_token(client):
    """Access and refresh tokens are not interchangeable."""
    created, cookies = _signup_session(client)
    bad_cookies = {**cookies, REFRESH_COOKIE_NAME: created["tokens"]["access_token"]}
    assert _refresh(client, bad_cookies).status_code == 401


def test_logout_revokes_only_this_device(client):
    created, cookies_a = _signup_session(client)
    other, cookies_b = _login_session(client, created["user"]["email"])

    client.cookies.clear()
    for key, value in cookies_a.items():
        client.cookies.set(key, value)
    resp = client.post(
        "/api/v1/auth/logout",
        json={"all_devices": False},
        headers=auth_headers(created),
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] == 1
    # The logout response clears this device's cookies.
    assert resp.cookies.get(REFRESH_COOKIE_NAME) in (None, "")

    assert _refresh(client, cookies_a).status_code == 401
    assert _refresh(client, cookies_b).status_code == 200


def test_logout_all_devices_revokes_every_session(client):
    created, cookies_a = _signup_session(client)
    other, cookies_b = _login_session(client, created["user"]["email"])

    client.cookies.clear()
    for key, value in cookies_a.items():
        client.cookies.set(key, value)
    resp = client.post(
        "/api/v1/auth/logout",
        json={"all_devices": True},
        headers=auth_headers(created),
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] == 2

    assert _refresh(client, cookies_a).status_code == 401
    assert _refresh(client, cookies_b).status_code == 401


def test_logout_requires_authentication(client):
    client.cookies.clear()
    assert client.post("/api/v1/auth/logout", json={}).status_code == 401


def test_concurrent_refresh_of_the_same_token_only_one_wins(client):
    """Rotation is a single conditional UPDATE, so a double-submit cannot fork
    the session into two live descendants."""
    created, cookies = _signup_session(client)
    raw = cookies[REFRESH_COOKIE_NAME]

    successes: list[int] = []
    failures: list[int] = []
    lock = threading.Lock()

    def rotate():
        app_eng = create_engine(settings.database_url, future=True)
        svc_eng = create_engine(settings.service_database_url, future=True)
        maker = sessionmaker(class_=Session, expire_on_commit=False)
        app_db, service_db = maker(bind=app_eng), maker(bind=svc_eng)
        try:
            refresh_service(app_db, service_db, raw_refresh_token=raw)
            with lock:
                successes.append(1)
        except InvalidRefreshToken:
            with lock:
                failures.append(1)
        finally:
            app_db.close()
            service_db.close()
            app_eng.dispose()
            svc_eng.dispose()

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: rotate(), range(8)))

    assert len(successes) == 1, f"expected 1 winner, got {len(successes)}"
    assert len(failures) == 7


def test_refresh_tokens_are_stored_hashed(client, service_db):
    created, cookies = _signup_session(client)
    raw = cookies[REFRESH_COOKIE_NAME]
    stored = service_db.execute(
        text("SELECT refresh_token_hash FROM user_sessions WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalars().all()
    assert raw not in stored
    assert all(len(h) == 64 for h in stored)
