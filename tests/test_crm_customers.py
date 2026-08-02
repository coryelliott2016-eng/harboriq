"""Customer CRUD over HTTP, against a real Postgres with RLS armed."""
from __future__ import annotations

from tests.conftest import auth_headers, invite, signup


def _create(client, actor, **fields):
    body = {"last_name": "Halyard", **fields}
    return client.post("/api/v1/customers", json=body, headers=auth_headers(actor))


def test_create_and_read_back(client):
    owner = signup(client)
    resp = _create(
        client,
        owner,
        first_name="Dana",
        email="dana@example.com",
        phone="555-0100",
        city="Newport",
        notes="prefers morning haul-outs",
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["first_name"] == "Dana"
    assert created["company_id"] == owner["user"]["company_id"]

    fetched = client.get(
        f"/api/v1/customers/{created['id']}", headers=auth_headers(owner)
    )
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_a_customer_must_have_at_least_one_name(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/customers", json={"city": "Newport"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 422


def test_blank_strings_are_not_a_name(client):
    """A web form posts '' rather than null; '' must not satisfy the name rule."""
    owner = signup(client)
    resp = client.post(
        "/api/v1/customers",
        json={"first_name": "   ", "last_name": "", "company_name": ""},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_patch_updates_only_the_fields_sent(client):
    owner = signup(client)
    created = _create(client, owner, first_name="Dana", city="Newport").json()

    resp = client.patch(
        f"/api/v1/customers/{created['id']}",
        json={"city": "Bristol"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["city"] == "Bristol"
    assert patched["first_name"] == "Dana"
    assert patched["updated_at"] >= created["updated_at"]


def test_patch_cannot_erase_every_name(client):
    """The DB CHECK is the authority for the merged row, and it answers 422."""
    owner = signup(client)
    created = _create(client, owner).json()

    resp = client.patch(
        f"/api/v1/customers/{created['id']}",
        json={"last_name": None},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_delete_then_404(client):
    owner = signup(client)
    created = _create(client, owner).json()

    assert client.delete(
        f"/api/v1/customers/{created['id']}", headers=auth_headers(owner)
    ).status_code == 204
    assert client.get(
        f"/api/v1/customers/{created['id']}", headers=auth_headers(owner)
    ).status_code == 404


def test_delete_is_refused_while_a_vessel_references_the_customer(client):
    owner = signup(client)
    customer = _create(client, owner).json()
    client.post(
        "/api/v1/vessels",
        json={"customer_id": customer["id"], "name": "Second Wind"},
        headers=auth_headers(owner),
    )

    resp = client.delete(
        f"/api/v1/customers/{customer['id']}", headers=auth_headers(owner)
    )
    assert resp.status_code == 409
    assert "vessels or jobs" in resp.json()["detail"]


def test_search_matches_name_email_and_phone(client):
    owner = signup(client)
    _create(client, owner, first_name="Dana", last_name="Halyard")
    _create(client, owner, last_name="Keel", email="skipper@marina.example.com")
    _create(client, owner, last_name="Transom", phone="555-0199")

    def search(term):
        resp = client.get(
            "/api/v1/customers", params={"search": term}, headers=auth_headers(owner)
        )
        assert resp.status_code == 200, resp.text
        return [row["last_name"] for row in resp.json()]

    assert search("Halyard") == ["Halyard"]
    assert search("skipper@") == ["Keel"]
    assert search("0199") == ["Transom"]
    assert search("Dana Halyard") == ["Halyard"]


def test_search_does_not_treat_a_wildcard_as_a_wildcard(client):
    """A user typing % is looking for a percent sign, not asking for every row."""
    owner = signup(client)
    _create(client, owner, last_name="Halyard")

    for term in ("%", "_", "Hal_ard", "\\"):
        resp = client.get(
            "/api/v1/customers", params={"search": term}, headers=auth_headers(owner)
        )
        assert resp.json() == [], term


def test_list_is_paginated(client):
    owner = signup(client)
    for n in range(5):
        _create(client, owner, last_name=f"Owner{n}")

    page = client.get(
        "/api/v1/customers",
        params={"limit": 2, "offset": 2},
        headers=auth_headers(owner),
    ).json()
    assert [row["last_name"] for row in page] == ["Owner2", "Owner3"]


def test_a_technician_can_read_but_not_write(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer = _create(client, owner, first_name="Dana").json()

    assert client.get("/api/v1/customers", headers=auth_headers(tech)).status_code == 200
    assert _create(client, tech, first_name="Sneaky").status_code == 403
    assert client.patch(
        f"/api/v1/customers/{customer['id']}",
        json={"city": "Nope"},
        headers=auth_headers(tech),
    ).status_code == 403
    assert client.delete(
        f"/api/v1/customers/{customer['id']}", headers=auth_headers(tech)
    ).status_code == 403


def test_office_staff_can_write(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    assert _create(client, office, first_name="Dana").status_code == 201


def test_customers_require_authentication(client):
    assert client.get("/api/v1/customers").status_code == 401
    assert client.post("/api/v1/customers", json={"last_name": "X"}).status_code == 401
