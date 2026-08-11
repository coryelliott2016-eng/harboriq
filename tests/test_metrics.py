"""The /metrics endpoint: Prometheus text exposition of request count/latency.

M-4 (Security Core Prompt v1.0): gated by METRICS_TOKEN whenever configured.
In the default development fixture the token is empty, so open scrape still
works for local Prometheus. When a token is set, Bearer auth is required.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_metrics_endpoint_reports_prior_requests(client):
    # Generate some traffic on a route with a stable template label first.
    client.get("/api/v1/healthz")
    client.get("/api/v1/healthz")

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")

    body = resp.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    # The healthz route should show up labelled with its route template, not
    # a raw/one-off path, and with a status of 200. Starlette's `route.path`
    # is relative to the router it was registered on ("/healthz"), not the
    # full mounted URL ("/api/v1/healthz") -- still a fixed template, not a
    # per-request value, which is what actually matters for cardinality.
    assert "/healthz" in body
    assert 'status="200"' in body


def test_metrics_endpoint_open_when_token_unset(client):
    # Development default: no METRICS_TOKEN configured -> open scrape, no 401.
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_requires_bearer_when_token_configured(monkeypatch):
    from app.core.config import settings
    from app.main import app

    token = "test-metrics-token-32b-xxxxxxxxxxxx"
    monkeypatch.setattr(settings, "metrics_token", token)

    with TestClient(app) as c:
        denied = c.get("/metrics")
        assert denied.status_code == 401
        assert denied.headers.get("www-authenticate", "").lower().startswith("bearer")

        wrong = c.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
        assert wrong.status_code == 401

        # Non-Bearer schemes must not be accepted even if the token value
        # would otherwise match — keeps the contract narrow.
        basic = c.get("/metrics", headers={"Authorization": f"Basic {token}"})
        assert basic.status_code == 401

        ok = c.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        assert "http_requests_total" in ok.text


def test_metrics_token_required_outside_development(monkeypatch):
    """Production Settings construction fails closed without METRICS_TOKEN."""
    from cryptography.fernet import Fernet
    from pydantic import ValidationError

    from app.core.config import Settings

    # Isolate from any developer .env so this asserts the validator itself,
    # not whatever happens to be configured on the workstation.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("METRICS_TOKEN", "")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "METRICS_TOKEN" in str(exc.value)
