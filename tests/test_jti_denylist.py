"""Access-token (JTI) denylist (Phase 17, Area C.1).

Covers: a logged-out access token stops working immediately (rather than
lingering until its natural `exp`), a fresh login after logout still
works normally, and Redis being unavailable fails open (a denylist check
never turns into a 500 for an otherwise-valid token).
"""
from __future__ import annotations

from unittest.mock import patch

from redis.exceptions import RedisError

from app.core.token_denylist import _reset_all_for_tests
from tests.conftest import auth_headers, login, signup


def setup_function(_fn):
    _reset_all_for_tests()


def test_access_token_stops_working_immediately_after_logout(client):
    owner = signup(client)
    headers = auth_headers(owner)

    ok = client.get("/api/v1/auth/me", headers=headers)
    assert ok.status_code == 200, ok.text

    logout_resp = client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert logout_resp.status_code == 200, logout_resp.text

    after = client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401, after.text


def test_a_fresh_login_after_logout_still_works(client):
    owner = signup(client)
    headers = auth_headers(owner)
    client.post("/api/v1/auth/logout", json={}, headers=headers)

    login_resp = login(client, owner["user"]["email"])
    new_headers = auth_headers(login_resp)

    ok = client.get("/api/v1/auth/me", headers=new_headers)
    assert ok.status_code == 200, ok.text


def test_other_sessions_access_tokens_are_unaffected_by_a_single_device_logout(client):
    """`all_devices=False` (the default) only denylists THIS token."""
    owner = signup(client)
    headers_a = auth_headers(owner)

    login_resp = login(client, owner["user"]["email"])
    headers_b = auth_headers(login_resp)

    client.post("/api/v1/auth/logout", json={}, headers=headers_a)

    still_ok = client.get("/api/v1/auth/me", headers=headers_b)
    assert still_ok.status_code == 200, still_ok.text

    revoked = client.get("/api/v1/auth/me", headers=headers_a)
    assert revoked.status_code == 401, revoked.text


def test_denylist_check_fails_open_when_redis_is_unavailable(client):
    owner = signup(client)
    headers = auth_headers(owner)
    client.post("/api/v1/auth/logout", json={}, headers=headers)

    # Without mocking, this token is now denylisted and would 401.
    denied = client.get("/api/v1/auth/me", headers=headers)
    assert denied.status_code == 401

    with patch("app.core.token_denylist.get_redis") as mock_get_redis:
        mock_get_redis.return_value.exists.side_effect = RedisError("boom")
        # Fails open: Redis being down must not turn a (still cryptographically
        # valid, unexpired) access token into a hard failure.
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200, resp.text


def test_logging_out_all_devices_still_denylists_the_calling_tokens_jti(client):
    owner = signup(client)
    headers = auth_headers(owner)

    resp = client.post("/api/v1/auth/logout", json={"all_devices": True}, headers=headers)
    assert resp.status_code == 200, resp.text

    after = client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401, after.text
