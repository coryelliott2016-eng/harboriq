import sys
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.observability import exclude_public_demo_telemetry, init_sentry

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("path", ["sessions", "assist"])
def test_demo_error_or_transaction_is_dropped_in_full(path):
    event = {
        "request": {"url": f"https://api.example.invalid/api/v1/public/intelligence/{path}"},
        "exception": {"values": [{"stacktrace": {"frames": [{"vars": {"session": "private"}}]}}]},
    }
    assert exclude_public_demo_telemetry(event, {}) is None


@pytest.mark.parametrize("transaction", [
    "POST /api/v1/public/intelligence/assist",
    "app.api.v1.routes.intelligence.assist",
])
def test_transaction_without_request_metadata_is_dropped(transaction):
    event = {"transaction": transaction}
    assert exclude_public_demo_telemetry(event, {}) is None


def test_proxy_root_path_is_also_excluded():
    event = {"request": {"url": "https://example.invalid/proxy/api/v1/public/intelligence/assist"}}
    assert exclude_public_demo_telemetry(event, {}) is None


@pytest.mark.parametrize("headers", [
    {"X-Demo-Session": "private"},
    [["x-demo-session", "private"]],
])
def test_custom_demo_header_cannot_escape_with_missing_url(headers):
    assert exclude_public_demo_telemetry({"request": {"headers": headers}}, {}) is None


def test_other_application_telemetry_preserved():
    event = {"request": {"url": "https://api.example.invalid/api/v1/jobs"}}
    assert exclude_public_demo_telemetry(event, {}) is event
    assert exclude_public_demo_telemetry({}, {}) == {}


def test_sentry_registers_both_filters(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "sentry_sdk", SimpleNamespace(init=lambda **kw: calls.append(kw)))
    monkeypatch.setattr(settings, "sentry_dsn", "https://example.invalid")
    init_sentry()
    assert calls[0]["before_send"] is exclude_public_demo_telemetry
    assert calls[0]["before_send_transaction"] is exclude_public_demo_telemetry
