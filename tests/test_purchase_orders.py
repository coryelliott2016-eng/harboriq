"""Purchase orders: draft creation, submit, receive (full & partial), cancel.

Also proves the guarded increment writer: receiving a PO line item raises
`quantity_on_hand` through the SAME kind of `FOR UPDATE`-guarded update
`app.services.inventory` already uses to decrement it on `POST /inventory/use`.
"""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, invite, make_inventory, signup


def _vendor_id(client, owner) -> str:
    resp = client.post(
        "/api/v1/vendors", json={"name": "Acme Marine Supply"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _draft(client, owner, vendor_id, item_id, qty=10, unit_cost="5.00"):
    return client.post(
        "/api/v1/purchase-orders",
        json={
            "vendor_id": vendor_id,
            "line_items": [
                {"inventory_item_id": item_id, "quantity_ordered": qty, "unit_cost": unit_cost}
            ],
        },
        headers=auth_headers(owner),
    )


def test_create_draft_with_line_items(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Prop Nut", qty=0))

    resp = _draft(client, owner, vendor_id, item_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["submitted_at"] is None
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["quantity_received"] == 0


def test_draft_needs_at_least_one_line_item(client):
    owner = signup(client)
    vendor_id = _vendor_id(client, owner)
    resp = client.post(
        "/api/v1/purchase-orders",
        json={"vendor_id": vendor_id, "line_items": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_draft_needs_a_vendor_that_exists_in_this_tenant(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    item_id = str(make_inventory(service_db, company_id, "Gasket", qty=0))

    resp = _draft(client, owner, str(uuid.uuid4()), item_id)
    assert resp.status_code == 404


def test_submit_moves_draft_to_submitted(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Zinc Anode", qty=0))
    po = _draft(client, owner, vendor_id, item_id).json()

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["submitted_at"] is not None


def test_cannot_submit_twice(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Hose Clamp", qty=0))
    po = _draft(client, owner, vendor_id, item_id).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    assert resp.status_code == 409


def test_receiving_increments_quantity_on_hand(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Bilge Pump", qty=2))
    po = _draft(client, owner, vendor_id, item_id, qty=10).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    line_id = po["line_items"][0]["id"]

    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"receipts": [{"line_item_id": line_id, "quantity": 10}]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "received"
    assert body["received_at"] is not None
    assert body["line_items"][0]["quantity_received"] == 10

    item = client.get(f"/api/v1/inventory/{item_id}", headers=auth_headers(owner)).json()
    assert item["quantity_on_hand"] == 12  # 2 already on hand + 10 received


def test_partial_receipt_across_two_lines_accumulates_correctly(client, service_db):
    """A PO with two line items, only one received: proves partial receipt
    is tracked per-line (`quantity_received` on the untouched line stays 0)
    while the PO itself still moves to `received` -- see
    `app.services.purchase_orders.receive`'s docstring for why "received"
    means "this shipment event happened", not "every unit arrived"."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_a = str(make_inventory(service_db, company_id, "Fuel Filter A", qty=0))
    item_b = str(make_inventory(service_db, company_id, "Fuel Filter B", qty=0))
    po = client.post(
        "/api/v1/purchase-orders",
        json={
            "vendor_id": vendor_id,
            "line_items": [
                {"inventory_item_id": item_a, "quantity_ordered": 10, "unit_cost": "5.00"},
                {"inventory_item_id": item_b, "quantity_ordered": 6, "unit_cost": "3.00"},
            ],
        },
        headers=auth_headers(owner),
    ).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    line_a = next(li for li in po["line_items"] if li["inventory_item_id"] == item_a)["id"]

    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"receipts": [{"line_item_id": line_a, "quantity": 4}]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "received"
    lines_by_item = {li["inventory_item_id"]: li for li in body["line_items"]}
    assert lines_by_item[item_a]["quantity_received"] == 4
    assert lines_by_item[item_b]["quantity_received"] == 0  # never receipted

    item_a_after = client.get(f"/api/v1/inventory/{item_a}", headers=auth_headers(owner)).json()
    item_b_after = client.get(f"/api/v1/inventory/{item_b}", headers=auth_headers(owner)).json()
    assert item_a_after["quantity_on_hand"] == 4
    assert item_b_after["quantity_on_hand"] == 0


def test_cannot_receive_more_than_was_ordered(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Fuel Filter", qty=0))
    po = _draft(client, owner, vendor_id, item_id, qty=10).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    line_id = po["line_items"][0]["id"]

    over = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"receipts": [{"line_item_id": line_id, "quantity": 100}]},
        headers=auth_headers(owner),
    )
    assert over.status_code == 422

    # Rejected atomically: no partial write should have happened.
    item = client.get(f"/api/v1/inventory/{item_id}", headers=auth_headers(owner)).json()
    assert item["quantity_on_hand"] == 0


def test_cannot_receive_a_draft_that_was_never_submitted(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "O-Ring", qty=0))
    po = _draft(client, owner, vendor_id, item_id).json()
    line_id = po["line_items"][0]["id"]

    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"receipts": [{"line_item_id": line_id, "quantity": 1}]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409


def test_cancel_a_draft(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Cotter Pin", qty=0))
    po = _draft(client, owner, vendor_id, item_id).json()

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=auth_headers(owner))
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cannot_cancel_a_received_po(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Cleat", qty=0))
    po = _draft(client, owner, vendor_id, item_id, qty=1).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth_headers(owner))
    line_id = po["line_items"][0]["id"]
    client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"receipts": [{"line_item_id": line_id, "quantity": 1}]},
        headers=auth_headers(owner),
    )

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=auth_headers(owner))
    assert resp.status_code == 409


def test_list_can_filter_by_status(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Trim Tab", qty=0))
    draft_po = _draft(client, owner, vendor_id, item_id).json()
    submitted_po = _draft(client, owner, vendor_id, item_id).json()
    client.post(
        f"/api/v1/purchase-orders/{submitted_po['id']}/submit", headers=auth_headers(owner)
    )

    resp = client.get(
        "/api/v1/purchase-orders", params={"status": "draft"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    ids = {po["id"] for po in resp.json()}
    assert draft_po["id"] in ids
    assert submitted_po["id"] not in ids


def test_a_technician_cannot_create_submit_or_receive(client, service_db):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = _vendor_id(client, owner)
    item_id = str(make_inventory(service_db, company_id, "Winch Handle", qty=0))

    assert _draft(client, tech, vendor_id, item_id).status_code == 403


def test_two_tenants_do_not_see_each_others_purchase_orders(client, service_db):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    company_a = uuid.UUID(a["user"]["company_id"])
    vendor_a = _vendor_id(client, a)
    item_a = str(make_inventory(service_db, company_a, "Tenant A Part", qty=0))
    po = _draft(client, a, vendor_a, item_a).json()

    resp = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=auth_headers(b))
    assert resp.status_code == 404
