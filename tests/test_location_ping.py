"""`POST /users/me/location-ping` and `GET /users/technician-locations`
(Phase 11).

Covers: a ping updates coordinates + timestamp, tenant isolation, and
lat/lng bounds validation. See `app/services/users.py::ping_location`/
`list_technician_locations`.
"""
from __future__ import annotations

from tests.conftest import auth_headers, invite, signup


def test_ping_updates_coordinates_and_timestamp(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")

    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.336700", "longitude": "-82.530700"},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_latitude"] == "27.336700"
    assert body["current_longitude"] == "-82.530700"
    assert body["location_updated_at"] is not None


def test_ping_can_be_updated_again_with_new_coordinates(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")

    client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.0", "longitude": "-82.0"},
        headers=auth_headers(tech),
    )
    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "28.0", "longitude": "-83.0"},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_latitude"] == "28.000000"
    assert body["current_longitude"] == "-83.000000"


def test_ping_requires_authentication(client):
    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.0", "longitude": "-82.0"},
    )
    assert resp.status_code == 401


def test_ping_rejects_latitude_out_of_bounds(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "127.0", "longitude": "-82.0"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_ping_rejects_longitude_out_of_bounds(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.0", "longitude": "-182.0"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_technician_locations_falls_back_to_home_base_without_a_ping(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"address_text": "some address"},
        headers=auth_headers(owner),
    )

    resp = client.get(
        "/api/v1/users/technician-locations", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    rows = {r["id"]: r for r in resp.json()}
    assert tech["user"]["id"] in rows
    assert rows[tech["user"]["id"]]["is_live"] is False


def test_technician_locations_shows_live_after_a_ping(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.0", "longitude": "-82.0"},
        headers=auth_headers(tech),
    )

    resp = client.get(
        "/api/v1/users/technician-locations", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    rows = {r["id"]: r for r in resp.json()}
    assert rows[tech["user"]["id"]]["is_live"] is True
    assert rows[tech["user"]["id"]]["latitude"] == "27.000000"


def test_technician_locations_is_tenant_isolated(client):
    owner_a = signup(client)
    tech_a = invite(client, owner_a, "technician")
    client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.0", "longitude": "-82.0"},
        headers=auth_headers(tech_a),
    )

    owner_b = signup(client)
    resp = client.get(
        "/api/v1/users/technician-locations", headers=auth_headers(owner_b)
    )
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert tech_a["user"]["id"] not in ids


def test_technician_locations_forbidden_for_technicians(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get(
        "/api/v1/users/technician-locations", headers=auth_headers(tech)
    )
    assert resp.status_code == 403, resp.text


def test_ping_flags_teleport_anomaly_but_still_accepts_coordinates(client):
    """A Sarasota -> Tokyo jump in one window is flagged, not rejected."""
    owner = signup(client)
    tech = invite(client, owner, "technician")
    headers = auth_headers(tech)

    first = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.336700", "longitude": "-82.530700"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["anomaly_suspected"] is False

    second = client.post(
        "/api/v1/users/me/location-ping",
        # Tokyo — ~12,000 km away; even over a few seconds this is >> 250 km/h.
        json={"latitude": "35.676200", "longitude": "139.650300"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["anomaly_suspected"] is True
    assert body["implied_speed_kmh"] is not None
    assert body["implied_speed_kmh"] > 250.0
    # Coordinates are still accepted (flag, don't hard-reject).
    assert body["current_latitude"] == "35.676200"
    assert body["current_longitude"] == "139.650300"


def test_ping_nearby_move_is_not_flagged_as_anomaly(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    headers = auth_headers(tech)

    client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.336700", "longitude": "-82.530700"},
        headers=headers,
    )
    # ~150 m away — well under any plausible-speed ceiling even in 1 second.
    resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.338000", "longitude": "-82.530700"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["anomaly_suspected"] is False


def test_location_ping_rate_limit_returns_429(client):
    """Per-user fixed window: exceeding the budget yields 429 + Retry-After."""
    from app.core.config import settings
    from app.core.rate_limit import _reset_all_for_tests

    owner = signup(client)
    tech = invite(client, owner, "technician")
    headers = auth_headers(tech)
    limit = settings.location_ping_rate_limit_per_window

    # Exhaust the budget. First ping has no prior fix so no anomaly noise.
    statuses = []
    for i in range(limit):
        resp = client.post(
            "/api/v1/users/me/location-ping",
            json={
                "latitude": f"{27.0 + (i * 0.0001):.6f}",
                "longitude": "-82.530700",
            },
            headers=headers,
        )
        statuses.append(resp.status_code)
    assert all(s == 200 for s in statuses), statuses

    blocked = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.500000", "longitude": "-82.530700"},
        headers=headers,
    )
    assert blocked.status_code == 429, blocked.text
    assert "Retry-After" in blocked.headers

    # A different user is not throttled by the first user's budget.
    other = invite(client, owner, "technician")
    other_resp = client.post(
        "/api/v1/users/me/location-ping",
        json={"latitude": "27.100000", "longitude": "-82.100000"},
        headers=auth_headers(other),
    )
    assert other_resp.status_code == 200, other_resp.text

    _reset_all_for_tests()

