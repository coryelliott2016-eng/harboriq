"""CORS middleware is mounted so the (separately-hosted) React frontend can
call the API cross-origin.

This only asserts the middleware is actually wired up and honours the
configured allowlist; it is not a re-test of Starlette's CORSMiddleware
itself, which has its own upstream test suite.
"""
from __future__ import annotations

from app.core.config import settings


def test_preflight_reflects_an_allowed_origin(client):
    origin = settings.cors_allow_origins[0]
    resp = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_actual_response_carries_the_cors_header_for_an_allowed_origin(client):
    origin = settings.cors_allow_origins[0]
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password-here"},
        headers={"Origin": origin},
    )
    # Any status is fine here (401 is expected) — what matters is the header.
    assert resp.headers.get("access-control-allow-origin") == origin


def test_preflight_does_not_reflect_a_disallowed_origin(client):
    resp = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {
        k.lower() for k in resp.headers.keys()
    } or resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
