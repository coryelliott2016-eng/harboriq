"""Unit tests for `app/services/geocoding.py`.

All tests here mock `httpx.get` — no real network calls. `test_dispatch_
candidates.py` / the manual smoke test are where a real (or DB-seeded)
coordinate pair proves the dispatch-scoring integration; this file is only
about the Nominatim client's own contract: happy path, every failure mode
degrading to `None` instead of raising, and the rate limiter.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.services import geocoding


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json_error = raise_json_error

    def json(self):
        if self._raise_json_error:
            raise ValueError("invalid json")
        return self._json_data


@pytest.fixture(autouse=True)
def _reset_throttle_state():
    """Each test gets a clean rate-limiter clock so tests don't sleep for
    real due to leftover state from a previous test in the same process."""
    geocoding._last_call_monotonic = None
    yield
    geocoding._last_call_monotonic = None


def test_geocode_happy_path_returns_lat_lon():
    fake = _FakeResponse(
        200, [{"lat": "27.3364", "lon": "-82.5307", "display_name": "Sarasota, FL"}]
    )
    with patch("httpx.get", return_value=fake) as mocked_get:
        result = geocoding.geocode("1100 23rd Street, Sarasota, FL 34234")
    assert result == (Decimal("27.3364"), Decimal("-82.5307"))
    # Confirms the Nominatim usage-policy User-Agent header is sent.
    _, kwargs = mocked_get.call_args
    assert "HarborIQ" in kwargs["headers"]["User-Agent"]


def test_geocode_returns_none_for_blank_address():
    with patch("httpx.get") as mocked_get:
        assert geocoding.geocode("") is None
        assert geocoding.geocode("   ") is None
        assert geocoding.geocode(None) is None  # type: ignore[arg-type]
    mocked_get.assert_not_called()


def test_geocode_returns_none_on_no_results():
    with patch("httpx.get", return_value=_FakeResponse(200, [])):
        assert geocoding.geocode("somewhere that does not exist") is None


def test_geocode_returns_none_on_non_200():
    with patch("httpx.get", return_value=_FakeResponse(503, None)):
        assert geocoding.geocode("123 Main St") is None


def test_geocode_returns_none_on_invalid_json():
    with patch("httpx.get", return_value=_FakeResponse(200, raise_json_error=True)):
        assert geocoding.geocode("123 Main St") is None


def test_geocode_returns_none_on_malformed_coordinates():
    with patch(
        "httpx.get", return_value=_FakeResponse(200, [{"lat": "not-a-number", "lon": "x"}])
    ):
        assert geocoding.geocode("123 Main St") is None


def test_geocode_returns_none_on_timeout():
    with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        assert geocoding.geocode("123 Main St") is None


def test_geocode_returns_none_on_connect_error():
    with patch("httpx.get", side_effect=httpx.ConnectError("no route to host")):
        assert geocoding.geocode("123 Main St") is None


def test_geocode_never_raises_on_unexpected_exception():
    """Even a totally unrelated bug inside the call path must not escape
    geocode() -- this is the "geocoding must never block a save" contract."""
    with patch("httpx.get", side_effect=RuntimeError("boom")):
        assert geocoding.geocode("123 Main St") is None


def test_throttle_enforces_minimum_interval_between_calls():
    fake = _FakeResponse(200, [{"lat": "1.0", "lon": "2.0"}])
    with patch("httpx.get", return_value=fake), patch(
        "time.sleep"
    ) as mocked_sleep, patch("time.monotonic", side_effect=[100.0, 100.0, 100.2, 100.2]):
        geocoding.geocode("first address")
        geocoding.geocode("second address")

    # The second call happened 0.2s after the first (per the mocked clock),
    # so the throttle should have slept for the remaining ~0.8s.
    assert mocked_sleep.called
    slept_for = mocked_sleep.call_args[0][0]
    assert 0.7 < slept_for <= 1.0


def test_throttle_does_not_sleep_when_enough_time_has_passed():
    fake = _FakeResponse(200, [{"lat": "1.0", "lon": "2.0"}])
    with patch("httpx.get", return_value=fake), patch(
        "time.sleep"
    ) as mocked_sleep, patch(
        "time.monotonic", side_effect=[100.0, 100.0, 105.0, 105.0]
    ):
        geocoding.geocode("first address")
        geocoding.geocode("second address")

    mocked_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# End-to-end proof: geocoding a customer's address (via the real create/PATCH
# routes, Nominatim mocked) unlocks the dispatch engine's distance factor,
# which is otherwise neutral ("no technician/customer coordinates") per
# app/services/dispatch.py::_score_distance.
# ---------------------------------------------------------------------------

from tests.conftest import auth_headers as _auth_headers  # noqa: E402
from tests.conftest import invite as _invite  # noqa: E402
from tests.conftest import signup as _signup  # noqa: E402


def test_geocoded_customer_address_activates_dispatch_distance_scoring(client, service_db):
    owner = _signup(client)
    close_tech = _invite(client, owner, "technician")

    # Technician's home address is geocoded via the real PATCH /users/{id}
    # route -- Nominatim itself is mocked, but everything else (the route,
    # the service layer, the UPDATE) is exercised for real.
    with patch("app.services.geocoding.geocode", return_value=(Decimal("27.3400"), Decimal("-82.5300"))):
        resp = client.patch(
            f"/api/v1/users/{close_tech['user']['id']}",
            json={"address_text": "123 Dock Ave, Sarasota, FL"},
            headers=_auth_headers(close_tech),
        )
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["home_latitude"]) == 27.34

    # Customer's address is geocoded via the real POST /customers route.
    with patch("app.services.geocoding.geocode", return_value=(Decimal("27.3364"), Decimal("-82.5307"))):
        customer_resp = client.post(
            "/api/v1/customers",
            json={
                "last_name": "Halyard",
                "address_line1": "100 Main St",
                "city": "Sarasota",
                "state": "FL",
            },
            headers=_auth_headers(owner),
        )
    assert customer_resp.status_code == 201, customer_resp.text
    customer_id = customer_resp.json()["id"]
    assert float(customer_resp.json()["latitude"]) == 27.3364

    job_resp = client.post(
        "/api/v1/jobs",
        json={"customer_id": customer_id, "title": "Bottom cleaning"},
        headers=_auth_headers(owner),
    )
    assert job_resp.status_code == 201, job_resp.text
    job_id = job_resp.json()["id"]

    candidates = client.get(
        f"/api/v1/jobs/{job_id}/dispatch/candidates", headers=_auth_headers(owner)
    ).json()
    by_id = {c["technician_id"]: c for c in candidates}

    close = by_id[close_tech["user"]["id"]]
    assert close["score"]["breakdown"]["distance"] != "0.00"
    assert float(close["score"]["breakdown"]["distance"]) > 0

    # Sanity check against the "neutral" baseline documented in
    # dispatch.py::_score_distance: the owner (also a candidate) never had
    # coordinates set, so their distance factor stays exactly the neutral
    # value while the geocoded technician's does not.
    owner_candidate = by_id.get(owner["user"]["id"])
    if owner_candidate is not None:
        assert owner_candidate["score"]["breakdown"]["distance"] == "0.00"
