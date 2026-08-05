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
