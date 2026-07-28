"""Refresh-token rotation, reuse detection and logout."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services.auth import InvalidRefreshToken
from app.services.auth import refresh as refresh_service
from tests.conftest import auth_headers, signup


def _refresh(client, refresh_token: str):
    return client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})


def test_refresh_returns_a_new_pair(client):
    created = signup(client)
    resp = _refresh(client, created["tokens"]["refresh_token"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["user"]["id"] == created["user"]["id"]
    assert body["tokens"]["refresh_token"] != created["tokens"]["refresh_token"]
    # The new access token works.
    assert client.get("/api/v1/auth/me", headers=auth_headers(body)).status_code == 200


def test_rotation_invalidates_the_presented_token(client):
    created = signup(client)
    first = created["tokens"]["refresh_token"]
    assert _refresh(client, first).status_code == 200

    replay = _refresh(client, first)
    assert replay.status_code == 401
    assert replay.headers["WWW-Authenticate"] == "Bearer"


def test_reuse_revokes_the_whole_family(client, service_db):
    """Replaying a rotated token means it leaked — kill every descendant."""
    created = signup(client)
    rotated = _refresh(client, created["tokens"]["refresh_token"]).json()

    # Attacker replays the already-used token.
    assert _refresh(client, created["tokens"]["refresh_token"]).status_code == 401

    # The legitimate holder's current token is now dead too.
    assert _refresh(client, rotated["tokens"]["refresh_token"]).status_code == 401

    reasons = service_db.execute(
        text(
            "SELECT DISTINCT revoked_reason FROM user_sessions WHERE user_id = :uid"
        ),
        {"uid": created["user"]["id"]},
    ).scalars().all()
    assert reasons == ["reuse_detected"]


def test_reuse_detection_is_audited(client, service_db):
    created = signup(client)
    _refresh(client, created["tokens"]["refresh_token"])
    _refresh(client, created["tokens"]["refresh_token"])

    actions = service_db.execute(
        text("SELECT action FROM audit_log WHERE company_id = :cid"),
        {"cid": created["user"]["company_id"]},
    ).scalars().all()
    assert "auth.refresh_reuse_detected" in actions


def test_refresh_rejects_an_unknown_token(client):
    assert _refresh(client, "definitely-not-a-real-refresh-token").status_code == 401


def test_refresh_rejects_an_expired_session(client, service_db):
    created = signup(client)
    service_db.execute(
        text("UPDATE user_sessions SET expires_at = now() - interval '1 day' "
             "WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    )
    service_db.commit()

    assert _refresh(client, created["tokens"]["refresh_token"]).status_code == 401


def test_refresh_rejects_an_access_token(client):
    """Access and refresh tokens are not interchangeable."""
    created = signup(client)
    assert _refresh(client, created["tokens"]["access_token"]).status_code == 401


def test_logout_revokes_only_this_device(client):
    created = signup(client)
    other = client.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": "correct-horse-battery-staple"},
    ).json()

    resp = client.post(
        "/api/v1/auth/logout", json={"all_devices": False}, headers=auth_headers(created)
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] == 1

    assert _refresh(client, created["tokens"]["refresh_token"]).status_code == 401
    assert _refresh(client, other["tokens"]["refresh_token"]).status_code == 200


def test_logout_all_devices_revokes_every_session(client):
    created = signup(client)
    other = client.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": "correct-horse-battery-staple"},
    ).json()

    resp = client.post(
        "/api/v1/auth/logout", json={"all_devices": True}, headers=auth_headers(created)
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] == 2

    assert _refresh(client, created["tokens"]["refresh_token"]).status_code == 401
    assert _refresh(client, other["tokens"]["refresh_token"]).status_code == 401


def test_logout_requires_authentication(client):
    assert client.post("/api/v1/auth/logout", json={}).status_code == 401


def test_concurrent_refresh_of_the_same_token_only_one_wins(client):
    """Rotation is a single conditional UPDATE, so a double-submit cannot fork
    the session into two live descendants."""
    created = signup(client)
    raw = created["tokens"]["refresh_token"]

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
    created = signup(client)
    raw = created["tokens"]["refresh_token"]
    stored = service_db.execute(
        text("SELECT refresh_token_hash FROM user_sessions WHERE user_id = :uid"),
        {"uid": created["user"]["id"]},
    ).scalars().all()
    assert raw not in stored
    assert all(len(h) == 64 for h in stored)
