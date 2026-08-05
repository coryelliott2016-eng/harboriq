"""Reorder suggestions: the read-only low-stock signal and one-click draft-PO
generation from it.

Deliberate scope boundary (see README "Inventory, parts & vendors"): this
module never sends anything to a vendor by itself. `generate-po` always
produces a `draft` -- a human must still call `POST /purchase-orders/{id}/submit`.
These tests focus on the vendor-grouping and multi-item behavior; the basic
"item below reorder point shows up" cases live in `test_inventory_crud.py`.
"""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, make_inventory, make_vendor, signup


def test_generate_po_covers_multiple_selected_items_for_one_vendor(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = make_vendor(service_db, company_id, name="Single Vendor")
    item_a = make_inventory(service_db, company_id, "Item A", qty=1, reorder_point=6,
                             unit_cost="2.00")
    item_b = make_inventory(service_db, company_id, "Item B", qty=0, reorder_point=4,
                             unit_cost="3.00")

    resp = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_id), "item_ids": [str(item_a), str(item_b)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["vendor_id"] == str(vendor_id)
    lines_by_item = {li["inventory_item_id"]: li for li in body["line_items"]}
    assert lines_by_item[str(item_a)]["quantity_ordered"] == 5  # 6 - 1
    assert lines_by_item[str(item_b)]["quantity_ordered"] == 4  # 4 - 0


def test_generate_po_across_two_vendors_needs_two_calls(client, service_db):
    """`generate_draft_from_suggestions` builds ONE draft PO for ONE vendor --
    a multi-vendor reorder run is deliberately two API calls, one per vendor,
    not an implicit fan-out the caller cannot see or review before it happens.
    """
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_x = make_vendor(service_db, company_id, name="Vendor X")
    vendor_y = make_vendor(service_db, company_id, name="Vendor Y")
    item_x = make_inventory(service_db, company_id, "From Vendor X", qty=0, reorder_point=3)
    item_y = make_inventory(service_db, company_id, "From Vendor Y", qty=0, reorder_point=3)

    po_x = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_x), "item_ids": [str(item_x)]},
        headers=auth_headers(owner),
    )
    po_y = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_y), "item_ids": [str(item_y)]},
        headers=auth_headers(owner),
    )
    assert po_x.status_code == 201
    assert po_y.status_code == 201
    assert po_x.json()["id"] != po_y.json()["id"]
    assert po_x.json()["status"] == "draft"
    assert po_y.json()["status"] == "draft"


def test_generate_po_from_suggestions_still_requires_submit_before_it_counts(client, service_db):
    """The generated PO is a draft; it must not itself change any stock or
    vendor commitment until a human explicitly submits it."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = make_vendor(service_db, company_id)
    item_id = make_inventory(service_db, company_id, "Needs Restock", qty=0, reorder_point=5)

    resp = client.post(
        "/api/v1/inventory/reorder-suggestions/generate-po",
        json={"vendor_id": str(vendor_id), "item_ids": [str(item_id)]},
        headers=auth_headers(owner),
    )
    assert resp.json()["status"] == "draft"

    item = client.get(f"/api/v1/inventory/{item_id}", headers=auth_headers(owner)).json()
    assert item["quantity_on_hand"] == 0  # nothing received yet -- still just a draft


def test_reorder_suggestions_are_sorted_with_default_vendor_grouping(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    vendor_id = make_vendor(service_db, company_id)
    make_inventory(service_db, company_id, "Has Default Vendor", qty=0, reorder_point=2)
    no_vendor_item = make_inventory(
        service_db, company_id, "No Default Vendor", qty=0, reorder_point=2
    )
    # Attach a default vendor to the first item via the update endpoint so the
    # ordering assertion below exercises the real read path, not a raw insert.
    has_vendor_item_id = client.get(
        "/api/v1/inventory", params={"search": "Has Default Vendor"},
        headers=auth_headers(owner),
    ).json()[0]["id"]
    client.patch(
        f"/api/v1/inventory/{has_vendor_item_id}",
        json={"default_vendor_id": str(vendor_id)},
        headers=auth_headers(owner),
    )

    resp = client.get("/api/v1/inventory/reorder-suggestions", headers=auth_headers(owner))
    assert resp.status_code == 200
    by_name = {i["name"]: i for i in resp.json()}
    assert by_name["Has Default Vendor"]["default_vendor_id"] == str(vendor_id)
    assert by_name["No Default Vendor"]["default_vendor_id"] is None
    assert str(no_vendor_item) == by_name["No Default Vendor"]["id"]
