"""Vessel CRUD, ownership, and the hull-id uniqueness rule."""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, invite, signup


def _customer(client, actor, last_name="Halyard") -> str:
    resp = client.post(
        "/api/v1/customers", json={"last_name": last_name}, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _vessel(client, actor, customer_id, **fields):
    body = {"customer_id": customer_id, "name": "Second Wind", **fields}
    return client.post("/api/v1/vessels", json=body, headers=auth_headers(actor))


def test_create_with_the_full_spec_sheet(client):
    owner = signup(client)
    customer = _customer(client, owner)

    resp = _vessel(
        client,
        owner,
        customer,
        make="Grady-White",
        model="Canyon 306",
        year=2019,
        hull_id="NTL30601J920",
        registration="RI 1234 AB",
        length_ft="30.50",
        beam_ft="10.25",
        draft_ft="2.00",
        engine_make="Yamaha",
        engine_model="F300",
        engine_hours=412,
        engine_count=2,
        storage_location="North Yard",
        slip_number="B-14",
        notes="needs new anodes",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["customer_id"] == customer
    assert body["engine_count"] == 2
    assert body["length_ft"] == "30.50"


def test_engine_count_defaults_to_one_when_omitted(client):
    owner = signup(client)
    vessel = _vessel(client, owner, _customer(client, owner)).json()
    assert vessel["engine_count"] == 1


def test_a_vessel_needs_a_customer_that_exists_in_this_tenant(client):
    owner = signup(client)
    resp = _vessel(client, owner, str(uuid.uuid4()))
    assert resp.status_code == 404


def test_hull_id_is_unique_within_a_tenant(client):
    owner = signup(client)
    customer = _customer(client, owner)
    assert _vessel(client, owner, customer, hull_id="NTL30601J920").status_code == 201

    resp = _vessel(client, owner, customer, hull_id="NTL30601J920", name="Copy")
    assert resp.status_code == 409
    assert "hull id" in resp.json()["detail"]


def test_two_tenants_may_each_record_the_same_hull_id(client):
    """Uniqueness is per company, not global."""
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    assert _vessel(client, a, _customer(client, a), hull_id="SHARED1").status_code == 201
    assert _vessel(client, b, _customer(client, b), hull_id="SHARED1").status_code == 201


def test_hull_id_may_be_null_for_many_vessels(client):
    """The uniqueness index is partial, so unknown hull ids do not collide."""
    owner = signup(client)
    customer = _customer(client, owner)
    assert _vessel(client, owner, customer, name="One").status_code == 201
    assert _vessel(client, owner, customer, name="Two").status_code == 201


def test_a_vessel_can_be_reassigned_when_the_boat_changes_hands(client):
    owner = signup(client)
    seller = _customer(client, owner, "Seller")
    buyer = _customer(client, owner, "Buyer")
    vessel = _vessel(client, owner, seller).json()

    resp = client.patch(
        f"/api/v1/vessels/{vessel['id']}",
        json={"customer_id": buyer},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["customer_id"] == buyer


def test_a_vessel_cannot_be_orphaned(client):
    owner = signup(client)
    vessel = _vessel(client, owner, _customer(client, owner)).json()

    resp = client.patch(
        f"/api/v1/vessels/{vessel['id']}",
        json={"customer_id": None},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_a_vessel_cannot_be_moved_to_another_tenants_customer(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    vessel = _vessel(client, a, _customer(client, a)).json()
    outsider = _customer(client, b, "Outsider")

    resp = client.patch(
        f"/api/v1/vessels/{vessel['id']}",
        json={"customer_id": outsider},
        headers=auth_headers(a),
    )
    assert resp.status_code == 404


def test_out_of_range_dimensions_are_rejected_before_the_database(client):
    owner = signup(client)
    customer = _customer(client, owner)
    assert _vessel(client, owner, customer, length_ft="100000").status_code == 422
    assert _vessel(client, owner, customer, length_ft="0").status_code == 422
    assert _vessel(client, owner, customer, year=1200).status_code == 422
    assert _vessel(client, owner, customer, engine_hours=-1).status_code == 422


def test_filter_and_nested_listing_by_customer(client):
    owner = signup(client)
    one = _customer(client, owner, "One")
    two = _customer(client, owner, "Two")
    _vessel(client, owner, one, name="Alpha")
    _vessel(client, owner, one, name="Beta")
    _vessel(client, owner, two, name="Gamma")

    flat = client.get(
        "/api/v1/vessels", params={"customer_id": one}, headers=auth_headers(owner)
    ).json()
    assert sorted(v["name"] for v in flat) == ["Alpha", "Beta"]

    nested = client.get(
        f"/api/v1/customers/{one}/vessels", headers=auth_headers(owner)
    ).json()
    assert sorted(v["name"] for v in nested) == ["Alpha", "Beta"]


def test_the_nested_listing_404s_for_an_unknown_customer(client):
    owner = signup(client)
    resp = client.get(
        f"/api/v1/customers/{uuid.uuid4()}/vessels", headers=auth_headers(owner)
    )
    assert resp.status_code == 404


def test_search_matches_the_spec_sheet(client):
    owner = signup(client)
    customer = _customer(client, owner)
    _vessel(client, owner, customer, name="Second Wind", make="Grady-White")
    _vessel(client, owner, customer, name="Knot Working", slip_number="B-14")

    def search(term):
        return [
            v["name"]
            for v in client.get(
                "/api/v1/vessels", params={"search": term}, headers=auth_headers(owner)
            ).json()
        ]

    assert search("Grady") == ["Second Wind"]
    assert search("B-14") == ["Knot Working"]


def test_delete_is_refused_while_a_job_references_the_vessel(client):
    owner = signup(client)
    customer = _customer(client, owner)
    vessel = _vessel(client, owner, customer).json()
    resp = client.post(
        "/api/v1/jobs",
        json={"customer_id": customer, "vessel_id": vessel["id"], "title": "Haul out"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text

    refused = client.delete(
        f"/api/v1/vessels/{vessel['id']}", headers=auth_headers(owner)
    )
    assert refused.status_code == 409


def test_a_technician_can_read_but_not_write(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer = _customer(client, owner)
    vessel = _vessel(client, owner, customer).json()

    assert client.get("/api/v1/vessels", headers=auth_headers(tech)).status_code == 200
    assert _vessel(client, tech, customer, name="Nope").status_code == 403
    assert client.delete(
        f"/api/v1/vessels/{vessel['id']}", headers=auth_headers(tech)
    ).status_code == 403
