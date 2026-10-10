"""No-DB coverage for consent, payload privacy and fail-closed analytics."""
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.api.v1.routes import marketing_events as routes
from app.core.config import Settings, settings
from app.schemas.marketing_events import MarketingEventCreate
from app.services import ai_demo, marketing_events

pytestmark = pytest.mark.no_db
PATH = "/api/v1/public/marketing-events"
EVENTS = [
    "homepage_view", "demo_launch", "category_select", "first_question",
    "ai_response", "demo_error", "early_access_click", "lead_submitted",
]


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """No unrelated auth limiter buckets are used by these tests."""


@pytest.fixture
def analytics(monkeypatch):
    monkeypatch.setattr(settings, "ai_demo_secret", "analytics-unit-test-secret-" * 3)
    backend = Mock()
    backend.eval.return_value = 0
    monkeypatch.setattr(ai_demo, "_redis_client", lambda: backend)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, backend


@pytest.mark.parametrize("event", EVENTS)
def test_whitelisted_consented_event_is_only_an_aggregate(analytics, event):
    client, backend = analytics
    response = client.post(PATH, json={"event": event, "consent": True})
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    script, key_count, *args = backend.eval.call_args.args
    assert script == marketing_events._EVENT_SCRIPT
    assert key_count == 3
    keys = args[:3]
    assert keys[2].endswith(f":{event}")
    assert ":daily:" in keys[2]
    assert keys[0].endswith(ai_demo._mac("marketing-events-ip-v1", "testclient"))
    assert "testclient" not in repr(args)
    assert all(isinstance(value, int) for value in args[3:])
    assert args[-1] <= 30 * 86400


@pytest.mark.parametrize("body", [
    {"event": "homepage_view"},
    {"event": "homepage_view", "consent": False},
    {"event": "homepage_view", "consent": 1},
    {"event": "homepage_view", "consent": "true"},
    {"event": "unknown", "consent": True},
    {"event": "homepage_view", "consent": True, "metadata": {}},
    {"event": "homepage_view", "consent": True, "message": "private prompt"},
    {"event": "homepage_view", "consent": True, "session_token": "anonymous session"},
    {"event": "homepage_view", "consent": True, "email": "visitor@example.com"},
    {"event": "homepage_view", "consent": True, "ip": "198.51.100.1"},
])
def test_unconsented_unknown_or_personal_payload_is_rejected(analytics, body):
    client, backend = analytics
    assert client.post(PATH, json=body).status_code == 422
    backend.eval.assert_not_called()


def test_schema_forbids_metadata_and_requires_literal_consent():
    schema = MarketingEventCreate.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"event", "consent"}
    assert schema["properties"]["consent"]["const"] is True


def test_forwarded_headers_do_not_select_the_limiter_identity(analytics):
    client, backend = analytics
    response = client.post(
        PATH, json={"event": "homepage_view", "consent": True},
        headers={"X-Forwarded-For": "198.51.100.8", "X-Real-IP": "198.51.100.9"},
    )
    assert response.status_code == 204
    key = backend.eval.call_args.args[2]
    assert key.endswith(ai_demo._mac("marketing-events-ip-v1", "testclient"))
    assert "198.51.100" not in repr(backend.eval.call_args)


def test_quota_rejection_is_fail_closed(analytics):
    client, backend = analytics
    backend.eval.return_value = 42
    response = client.post(PATH, json={"event": "demo_launch", "consent": True})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    backend.eval.assert_called_once()


def test_redis_outage_is_fail_closed(analytics):
    client, backend = analytics
    backend.eval.side_effect = ConnectionError("redis unavailable")
    response = client.post(PATH, json={"event": "demo_launch", "consent": True})
    assert response.status_code == 503
    assert response.json() == {"detail": "Analytics safety service is unavailable."}


def test_missing_secret_prevents_analytics_storage(analytics, monkeypatch):
    client, backend = analytics
    monkeypatch.setattr(settings, "ai_demo_secret", "")
    assert client.post(PATH, json={"event": "demo_launch", "consent": True}).status_code == 503
    backend.eval.assert_not_called()


@pytest.mark.parametrize("retention", [0, 31])
def test_retention_can_never_exceed_30_days(retention):
    with pytest.raises(ValueError):
        Settings(_env_file=None, marketing_events_retention_days=retention)


def test_full_app_analytics_never_accesses_customer_data_or_providers(analytics, monkeypatch):
    from sqlalchemy.engine import Engine

    from app.main import app

    forbidden = Mock(side_effect=AssertionError("No customer/provider access allowed"))
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr("httpx.post", forbidden)
    monkeypatch.setattr("httpx.AsyncClient.send", forbidden)
    with TestClient(app) as client:
        assert client.post(PATH, json={"event": "demo_launch", "consent": True}).status_code == 204
    forbidden.assert_not_called()


def test_real_redis_daily_counter_atomic_limits_retention_and_no_individual_storage(
    analytics, monkeypatch,
):
    url = os.environ.get("AI_DEMO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set AI_DEMO_TEST_REDIS_URL to exercise the real Redis Lua script")
    backend = redis.Redis.from_url(url, decode_responses=True)
    monkeypatch.setattr(ai_demo, "_redis_client", lambda: backend)
    monkeypatch.setattr(settings, "marketing_events_requests_per_ip", 3)
    monkeypatch.setattr(settings, "marketing_events_requests_global", 10)
    monkeypatch.setattr(settings, "marketing_events_window_seconds", 60)
    request = Request({
        "type": "http", "client": (f"test-{secrets.token_hex(16)}", 1234), "headers": [],
    })
    # The test Redis must be isolated: production keys are not flushed/deleted.
    assert backend.dbsize() == 0, "Use an empty dedicated Redis DB for analytics tests"

    def count(_):
        try:
            marketing_events.count_event(request, "homepage_view")
        except HTTPException as error:
            if error.status_code == 429:
                return False
            raise
        return True

    keys = []
    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            assert sum(workers.map(count, range(20))) == 3
        keys = backend.keys("harboriq:{marketing-events}:v1:*")
        assert len(keys) == 3
        aggregate = next(key for key in keys if ":daily:" in key)
        assert backend.get(aggregate) == "3"
        assert 0 < backend.ttl(aggregate) <= 30 * 86400
        assert all(0 < backend.ttl(key) <= 60 for key in keys if ":limit:" in key)
        assert request.client.host not in repr(keys)
        assert all(backend.type(key) == "string" for key in keys)
        monkeypatch.setattr(settings, "marketing_events_requests_per_ip", 10)
        monkeypatch.setattr(settings, "marketing_events_requests_global", 3)
        second = Request({"type": "http", "client": ("another-peer", 1234), "headers": []})
        with pytest.raises(HTTPException) as error:
            marketing_events.count_event(second, "demo_launch")
        assert error.value.status_code == 429
        assert backend.keys("harboriq:{marketing-events}:v1:*") == keys
        assert backend.get(aggregate) == "3"
    finally:
        if keys:
            backend.delete(*keys)
