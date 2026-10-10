from datetime import UTC, datetime
from threading import Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.api.v1.routes import intelligence
from app.core import demo_limits
from app.core.config import settings
from app.schemas.intelligence import Measurement
from app.services import noaa

pytestmark = pytest.mark.no_db


class FakeRedis:
    """Model the supported EVAL protocol, including TTL and atomic admission."""
    def __init__(self):
        self.values = {}
        self.expiry = {}
        self.now = 0
        self.lock = Lock()
        self.calls = []
        self.unavailable = False

    def eval(self, script, count, *args):
        with self.lock:
            if self.unavailable:
                raise ConnectionError("sensitive Redis connection string")
            self.calls.append((script, args))
            for key, expires in list(self.expiry.items()):
                if expires <= self.now:
                    self.values.pop(key, None)
                    del self.expiry[key]
            keys, argv = args[:count], args[count:]
            if script == demo_limits.CREATE_SESSION:
                ip, day, session = keys
                if self.values.get(ip, 0) >= 3 or self.values.get(day, 0) >= argv[0]:
                    return 0
                if session in self.values:
                    return -1
                for key, ttl in [(ip, argv[1]), (day, argv[2])]:
                    if key not in self.values:
                        self.expiry[key] = self.now + ttl
                    self.values[key] = self.values.get(key, 0) + 1
                self.values[session] = argv[3]
                self.expiry[session] = self.now + argv[1]
                return 1
            assert script == demo_limits.RESERVE_CALL
            session, day = keys
            if session not in self.values:
                return -1
            if self.values[session] <= 0:
                return -2
            if self.values.get(day, 0) >= argv[0]:
                return -3
            self.values[session] -= 1
            if day not in self.values:
                self.expiry[day] = self.now + argv[1]
            self.values[day] = self.values.get(day, 0) + 1
            return self.values[session]


@pytest.fixture
def demo(monkeypatch):
    store = FakeRedis()
    monkeypatch.setattr(demo_limits, "get_demo_redis", lambda: store)
    monkeypatch.setattr(settings, "intelligence_demo_enabled", True)
    monkeypatch.setattr(settings, "intelligence_demo_daily_noaa_budget", 100)
    monkeypatch.setattr(settings, "intelligence_demo_daily_session_budget", 1000)
    app = FastAPI()
    app.include_router(intelligence.router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, store


PREFIX = "/api/v1/public/intelligence"
BODY = {"sector": "service", "station": "8726520", "product": "water_level"}


def session(client, **kwargs):
    response = client.post(
        f"{PREFIX}/sessions", json={"accepted_safety_notice": True}, **kwargs,
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()["session_token"]


def request(client, token, body=None):
    return client.post(
        f"{PREFIX}/assist", headers={"X-Demo-Session": token}, json=body or BODY,
    )


def observation():
    now = datetime.now(UTC)
    return noaa.Observation(
        noaa.NOAA_URL + "?product=water_level", now, now,
        [Measurement(time=now.isoformat(), value="1.234", unit="ft MLLW")],
    )


def test_settings_default_disabled():
    assert type(settings).model_fields["intelligence_demo_enabled"].default is False


def test_disabled_never_contacts_redis_or_noaa(demo, monkeypatch):
    client, store = demo
    monkeypatch.setattr(settings, "intelligence_demo_enabled", False)
    assert client.post(f"{PREFIX}/sessions", json={"accepted_safety_notice": True}).status_code == 404
    assert request(client, "a" * 43).status_code == 404
    assert store.calls == []


@pytest.mark.parametrize("body", [
    {}, {"accepted_safety_notice": False}, {"accepted_safety_notice": 1},
    {"accepted_safety_notice": "true"}, {"accepted_safety_notice": True, "email": "private"},
])
def test_explicit_boolean_consent_only(demo, body):
    client, store = demo
    assert client.post(f"{PREFIX}/sessions", json=body).status_code == 422
    assert store.calls == []


def test_happy_response_and_shared_session_quota(demo, monkeypatch):
    client, store = demo
    calls = []
    monkeypatch.setattr(noaa, "fetch_water_level", lambda station: calls.append(station) or observation())
    token = session(client)
    for remaining in range(4, -1, -1):
        response = request(client, token)
        assert response.status_code == 200
        result = response.json()
        assert result["requests_remaining"] == remaining
        assert result["mode"] == "live_public_data"
        assert result["measurements"][0]["value"] == "1.234"
        assert "not AI diagnostics" in " ".join(result["warnings"])
        assert result["station"] == "8726520"
        assert "MLLW" in result["summary"]
        assert response.headers["cache-control"] == "no-store"
    assert request(client, token).status_code == 429
    assert len(calls) == 5
    assert all(token not in key for key in store.values)
    assert all("testclient" not in key for key in store.values)


def test_sessions_expire_and_do_not_refresh_ttl(demo):
    client, store = demo
    token = session(client)
    store.now = 899
    assert demo_limits.reserve_call(token) == 4
    store.now = 900
    assert request(client, token).status_code == 401
    assert not any(key.startswith("intelligence:session:") for key in store.values)


def test_per_ip_creation_limit_ignores_forwarded_headers(demo):
    client, _ = demo
    for i in range(3):
        session(client, headers={"X-Forwarded-For": f"192.0.2.{i}"})
    assert client.post(
        f"{PREFIX}/sessions", json={"accepted_safety_notice": True},
        headers={"X-Forwarded-For": "192.0.2.100"},
    ).status_code == 429


def test_global_session_budget(demo, monkeypatch):
    client, _ = demo
    monkeypatch.setattr(settings, "intelligence_demo_daily_session_budget", 1)
    session(client)
    assert client.post(f"{PREFIX}/sessions", json={"accepted_safety_notice": True}).status_code == 429


def test_shared_daily_upstream_budget(demo, monkeypatch):
    client, store = demo
    monkeypatch.setattr(settings, "intelligence_demo_daily_noaa_budget", 1)
    monkeypatch.setattr(noaa, "fetch_water_level", lambda station: observation())
    first, second = session(client), session(client)
    assert request(client, first).status_code == 200
    assert request(client, second).status_code == 503
    assert store.values[demo_limits._session_key(second)] == 5


def test_upstream_failure_spends_attempt_and_never_returns_fake_data(demo, monkeypatch):
    client, store = demo
    token = session(client)

    def fail(station):
        raise noaa.NOAAUnavailable("sensitive upstream details")

    monkeypatch.setattr(noaa, "fetch_water_level", fail)
    result = request(client, token)
    assert result.status_code == 502
    assert "sensitive" not in result.text
    assert "measurements" not in result.json()
    assert store.values[demo_limits._session_key(token)] == 4


def test_redis_failure_closed_for_both_routes(demo):
    client, store = demo
    token = session(client)
    store.unavailable = True
    for result in [
        request(client, token),
        client.post(f"{PREFIX}/sessions", json={"accepted_safety_notice": True}),
    ]:
        assert result.status_code == 503
        assert "sensitive" not in result.text


@pytest.mark.parametrize("body", [
    {**BODY, "station": "1234567"}, {**BODY, "station": "https://evil.example"},
    {**BODY, "sector": "private"}, {**BODY, "prompt": "private tenant data"},
    {**BODY, "product": "currents"},
])
def test_closed_allowlist_and_unsupported_currents(demo, body):
    client, store = demo
    assert request(client, "a" * 43, body).status_code == 422
    assert store.calls == []


def test_missing_and_unknown_session(demo):
    client, store = demo
    assert client.post(f"{PREFIX}/assist", json=BODY).status_code == 422
    assert request(client, "invalid").status_code == 422
    assert request(client, "!" * 43).status_code == 401
    assert store.calls == []
    assert request(client, "a" * 43).status_code == 401


def test_concurrent_requests_reserve_no_more_than_five(demo):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    client, _ = demo
    token = session(client)

    def reserve(_):
        try:
            return demo_limits.reserve_call(token)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(12)))
    assert sorted(value for value in results if value < 5) == list(range(5))
    assert results.count(429) == 7


@pytest.mark.parametrize("station", ["8726520", "8518750", "9414290"])
def test_marina_station_contract(demo, monkeypatch, station):
    client, _ = demo
    called = []
    monkeypatch.setattr(noaa, "fetch_water_level", lambda value: called.append(value) or observation())
    result = request(client, session(client), {**BODY, "station": station, "sector": "marina"})
    assert result.status_code == 200
    assert called == [station]
    assert result.json()["sector"] == "marina"
    assert "Marina planning" in result.json()["summary"]


def test_creation_keys_have_bounded_ttls_and_no_raw_ip(demo):
    client, store = demo
    session(client)
    assert len(store.values) == 3
    assert sorted(store.expiry.values()) == [900, 900, 172800]
    assert all("testclient" not in str(call) for call in store.calls)
