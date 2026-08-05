"""Vendor CRUD."""
from __future__ import annotations

from tests.conftest import auth_headers, invite, signup


def _vendor(client, actor, **fields):
    body = {"name": "Acme Marine Supply", **fields}
    return client.post("/api/v1/vendors", json=body, headers=auth_headers(actor))


def test_create_with_full_contact_info(client):
    owner = signup(client)
    resp = _vendor(
        client, owner,
        contact_email="orders@acmemarine.example",
        contact_phone="941-555-0100",
        notes="Net 30 terms",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Acme Marine Supply"
    assert body["contact_email"] == "orders@acmemarine.example"


def test_name_is_required(client):
    owner = signup(client)
    resp = client.post("/api/v1/vendors", json={}, headers=auth_headers(owner))
    assert resp.status_code == 422


def test_get_and_list_round_trip(client):
    owner = signup(client)
    created = _vendor(client, owner).json()

    got = client.get(f"/api/v1/vendors/{created['id']}", headers=auth_headers(owner))
    assert got.status_code == 200

    listed = client.get("/api/v1/vendors", headers=auth_headers(owner))
    assert listed.status_code == 200
    assert any(v["id"] == created["id"] for v in listed.json())


def test_search_matches_name(client):
    owner = signup(client)
    _vendor(client, owner, name="Yamaha Marine Parts")
    _vendor(client, owner, name="Mercury Distributors")

    resp = client.get(
        "/api/v1/vendors", params={"search": "yamaha"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    names = {v["name"] for v in resp.json()}
    assert names == {"Yamaha Marine Parts"}


def test_update_contact_info(client):
    owner = signup(client)
    created = _vendor(client, owner).json()

    resp = client.patch(
        f"/api/v1/vendors/{created['id']}",
        json={"contact_phone": "941-555-0199"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["contact_phone"] == "941-555-0199"


def test_a_technician_cannot_create_or_update_a_vendor(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")

    assert _vendor(client, tech).status_code == 403


def test_a_technician_can_still_read_vendors(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    _vendor(client, owner)

    resp = client.get("/api/v1/vendors", headers=auth_headers(tech))
    assert resp.status_code == 200


def test_two_tenants_do_not_see_each_others_vendors(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    _vendor(client, a, name="Tenant A Vendor")

    resp = client.get("/api/v1/vendors", headers=auth_headers(b))
    assert resp.status_code == 200
    assert resp.json() == []
