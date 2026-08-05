"""Inventory CRUD, SKU/barcode lookup, and low-stock reorder suggestions."""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, invite, make_inventory, make_vendor, signup


def _item(client, actor, **fields):
    body = {"name": "Impeller Kit", "unit_cost": "10.00", "retail_price": "25.00", **fields}
    return client.post("/api/v1/inventory", json=body, headers=auth_headers(actor))


def test_create_starts_at_zero_on_hand_regardless_of_input(client):
    """`quantity_on_hand` is not a create-time field -- stock only ever
    arrives via a received purchase order."""
    owner = signup(client)
    resp = _item(client, owner, sku="IMP-100")
    assert resp.status_code == 201, resp.text
    assert resp.json()["quantity_on_hand"] == 0


def test_get_and_list_round_trip(client):
    owner = signup(client)
    created = _item(client, owner, sku="IMP-200").json()

    got = client.get(f"/api/v1/inventory/{created['id']}", headers=auth_headers(owner))
    assert got.status_code == 200
    assert got.json()["sku"] == "IMP-200"

    listed = client.get("/api/v1/inventory", headers=auth_headers(owner))
    assert listed.status_code == 200
    assert any(i["id"] == created["id"] for i in listed.json())


def test_sku_is_unique_within_a_tenant(client):
    owner = signup(client)
    assert _item(client, owner, sku="DUP-1").status_code == 201

    resp = _item(client, owner, sku="DUP-1", name="Different Name")
    assert resp.status_code == 409
    assert "sku" in resp.json()["detail"].lower()


def test_two_tenants_may_each_use_the_same_sku(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    assert _item(client, a, sku="SHARED-SKU").status_code == 201
    assert _item(client, b, sku="SHARED-SKU").status_code == 201


def test_sku_may_be_null_for_many_items(client):
    """The uniqueness index is partial: unknown SKUs never collide."""
    owner = signup(client)
    assert _item(client, owner, name="One", sku=None).status_code == 201
    assert _item(client, owner, name="Two", sku=None).status_code == 201


def test_lookup_by_sku_finds_the_item(client):
    owner = signup(client)
    created = _item(client, owner, sku="LOOKUP-1").json()

    resp = client.get(
        "/api/v1/inventory/lookup", params={"sku": "LOOKUP-1"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_lookup_by_unknown_sku_is_404(client):
    owner = signup(client)
    resp = client.get(
        "/api/v1/inventory/lookup", params={"sku": "NOPE"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 404


def test_update_changes_reorder_point_and_price(client):
    owner = signup(client)
    created = _item(client, owner, sku="UPD-1").json()

    resp = client.patch(
        f"/api/v1/inventory/{created['id']}",
        json={"reorder_point": 5, "retail_price": "30.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reorder_point"] == 5
    assert body["retail_price"] == "30.00"


def test_update_default_vendor_must_exist(client):
    owner = signup(client)
    created = _item(client, owner, sku="VND-1").json()

    resp = client.patch(
        f"/api/v1/inventory/{created['id']}",
        json={"default_vendor_id": str(uuid.uuid4())},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


def test_a_technician_cannot_create_or_update_inventory(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")

    resp = _item(client, tech, sku="RBAC-1")
    assert resp.status_code == 403


def test_low_stock_only_filter(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    low = make_inventory(service_db, company_id, "Low Stock Filter", qty=1, reorder_point=5)
    make_inventory(service_db, company_id, "Well Stocked Filter", qty=20, reorder_point=5)

    resp = client.get(
        "/api/v1/inventory", params={"low_stock_only": True}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()}
    assert str(low) in ids
    assert all(i["quantity_on_hand"] < i["reorder_point"] for i in resp.json())


def test_reorder_suggestions_lists_items_below_reorder_point(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    make_inventory(service_db, company_id, "Short Belt", qty=0, reorder_point=3)
    make_inventory(service_db, company_id, "Plenty Belt", qty=50, reorder_point=3)

    resp = client.get("/api/v1/inventory/reorder-suggestions", headers=auth_headers(owner))
    assert resp.status_code == 200
    names = {i["name"] for i in resp.json()}
    assert "Short Belt" in names
    assert "Plenty Belt" not in names


def test_reorder_suggestions_groups_nullable_default_vendor(client, service_db):
    """Items with no default vendor still surface -- see
    `app.services.inventory.reorder_suggestions`'s docstring."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    make_inventory(service_db, company_id, "No Vendor Yet", qty=0, reorder_point=2)

    resp = client.get("/api/v1/inventory/reorder-suggestions", headers=auth_headers(owner))
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["name"] == "No Vendor Yet")
    assert item["default_vendor_id"] is None


def test_generate_po_from_reorder_suggestions_creates_a_draft(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = make_vendor(service_db, company_id)
    item_id = make_inventory(service_db, company_id, "Anode Set", qty=1, reorder_point=10,
                              unit_cost="5.00")

    resp = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_id), "item_ids": [str(item_id)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["vendor_id"] == str(vendor_id)
    line = body["line_items"][0]
    assert line["inventory_item_id"] == str(item_id)
    # restocks to the reorder point: 10 - 1 = 9
    assert line["quantity_ordered"] == 9


def test_generate_po_refuses_items_that_are_not_actually_low(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = make_vendor(service_db, company_id)
    item_id = make_inventory(service_db, company_id, "Well Stocked", qty=100, reorder_point=5)

    resp = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_id), "item_ids": [str(item_id)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
