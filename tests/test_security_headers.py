"""Baseline HTTP security response headers (Security Core Prompt v1.0, H-3 fix)."""
from __future__ import annotations

from app.core.config import settings


def test_security_headers_present_on_a_normal_response(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in resp.headers["Permissions-Policy"]
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_security_headers_present_on_error_responses_too(client):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_docs_get_a_relaxed_csp_instead_of_default_src_none(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "default-src 'none'" not in resp.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_hsts_is_absent_in_development(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    resp = client.get("/")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_is_present_outside_development(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    resp = client.get("/")
    assert resp.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
