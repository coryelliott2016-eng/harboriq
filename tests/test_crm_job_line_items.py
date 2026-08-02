"""Job line items — the labor/parts record that the invoicing phase will bill."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from tests.conftest import auth_headers, invite, make_inventory, signup
from tests.test_crm_jobs import make_customer, make_job


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _add(client, actor, job_id, **fields):
    body = {"kind": "labor", "description": "Diagnosis", "quantity": "1.00", **fields}
    return client.post(
        f"/api/v1/jobs/{job_id}/line-items", json=body, headers=auth_headers(actor)
    )


def test_line_total_is_computed_by_the_database(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _add(
        client, owner, job, description="Labor", quantity="1.50", unit_price="95.00"
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["line_total"] == "142.50"
    assert body["taxable"] is True
    assert body["invoice_id"] is None


def test_lines_appear_on_the_job_detail_in_order(client):
    owner = signup(client)
    job = _job(client, owner)
    _add(client, owner, job, description="Labor", quantity="2.00", unit_price="95.00")
    _add(client, owner, job, kind="fee", description="Shop supplies",
         quantity="1.00", unit_price="15.00")

    detail = client.get(f"/api/v1/jobs/{job}", headers=auth_headers(owner)).json()
    assert [item["description"] for item in detail["line_items"]] == [
        "Labor", "Shop supplies"
    ]


def test_quantity_must_be_positive_and_bounded(client):
    owner = signup(client)
    job = _job(client, owner)
    assert _add(client, owner, job, quantity="0").status_code == 422
    assert _add(client, owner, job, quantity="-1").status_code == 422
    assert _add(client, owner, job, quantity="99999999").status_code == 422
    assert _add(client, owner, job, quantity="1", unit_price="-1").status_code == 422


def test_only_a_part_line_may_name_an_inventory_item(client, service_db):
    owner = signup(client)
    job = _job(client, owner)
    item = make_inventory(
        service_db, uuid.UUID(owner["user"]["company_id"]), "Impeller", qty=5
    )

    assert _add(
        client, owner, job, kind="labor", inventory_item_id=str(item)
    ).status_code == 422
    assert _add(
        client, owner, job, kind="part", description="Impeller",
        inventory_item_id=str(item), quantity="1.00", unit_price="42.00",
    ).status_code == 201


def test_a_line_can_be_corrected_and_removed(client):
    owner = signup(client)
    job = _job(client, owner)
    line = _add(client, owner, job, quantity="1.00", unit_price="95.00").json()

    patched = client.patch(
        f"/api/v1/jobs/{job}/line-items/{line['id']}",
        json={"quantity": "2.00"},
        headers=auth_headers(owner),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["line_total"] == "190.00"

    assert client.delete(
        f"/api/v1/jobs/{job}/line-items/{line['id']}", headers=auth_headers(owner)
    ).status_code == 204
    assert client.get(
        f"/api/v1/jobs/{job}/line-items", headers=auth_headers(owner)
    ).json() == []


def test_an_unknown_line_is_a_404(client):
    owner = signup(client)
    job = _job(client, owner)
    resp = client.patch(
        f"/api/v1/jobs/{job}/line-items/{uuid.uuid4()}",
        json={"quantity": "2.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


def test_an_invoiced_line_is_frozen(client, service_db):
    """Forward-compatibility with invoicing: billed work stops being editable."""
    owner = signup(client)
    company_id = owner["user"]["company_id"]
    job = _job(client, owner)
    line = _add(client, owner, job, quantity="1.00", unit_price="95.00").json()

    invoice = service_db.execute(
        text(
            """
            INSERT INTO invoices (company_id, status, total, balance_due)
            VALUES (:cid, 'draft', '95.00', '95.00')
            RETURNING id
            """
        ),
        {"cid": company_id},
    ).first()
    service_db.execute(
        text(
            """
            UPDATE job_line_items
               SET invoice_id = :inv, invoiced_at = now()
             WHERE id = :id
            """
        ),
        {"inv": invoice[0], "id": line["id"]},
    )
    service_db.commit()

    patched = client.patch(
        f"/api/v1/jobs/{job}/line-items/{line['id']}",
        json={"quantity": "9.00"},
        headers=auth_headers(owner),
    )
    assert patched.status_code == 409
    assert "invoiced" in patched.json()["detail"]
    assert client.delete(
        f"/api/v1/jobs/{job}/line-items/{line['id']}", headers=auth_headers(owner)
    ).status_code == 409


def test_the_assigned_technician_records_their_own_work(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)
    client.post(
        f"/api/v1/jobs/{job}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    assert _add(client, tech, job, quantity="3.00", unit_price="95.00").status_code == 201


def test_a_technician_cannot_bill_a_job_they_are_not_on(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)

    assert _add(client, tech, job).status_code == 403


# ---------------------------------------------------------------------------
# the inventory link
# ---------------------------------------------------------------------------
def test_using_a_part_on_a_job_deducts_stock_and_bills_the_line(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    item = make_inventory(service_db, company_id, "Impeller", qty=5, retail="42.00")
    job = _job(client, owner)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(item), "quantity": 2, "job_id": job},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["remaining_on_hand"] == 3

    lines = client.get(
        f"/api/v1/jobs/{job}/line-items", headers=auth_headers(owner)
    ).json()
    assert len(lines) == 1
    assert lines[0]["kind"] == "part"
    assert lines[0]["inventory_committed"] is True
    assert lines[0]["inventory_item_id"] == str(item)
    assert lines[0]["quantity"] == "2.00"
    assert lines[0]["line_total"] == "84.00"


def test_a_failed_deduction_bills_nothing(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    item = make_inventory(service_db, company_id, "Impeller", qty=1)
    job = _job(client, owner)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(item), "quantity": 5, "job_id": job},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409
    assert client.get(
        f"/api/v1/jobs/{job}/line-items", headers=auth_headers(owner)
    ).json() == []


def test_an_unknown_job_leaves_stock_alone(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    item = make_inventory(service_db, company_id, "Impeller", qty=5)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(item), "quantity": 2, "job_id": str(uuid.uuid4())},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404

    remaining = service_db.execute(
        text("SELECT quantity_on_hand FROM inventory_items WHERE id = :id"),
        {"id": item},
    ).scalar_one()
    assert remaining == 5


def test_a_technician_cannot_bill_parts_to_a_job_they_are_not_on(client, service_db):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    company_id = uuid.UUID(owner["user"]["company_id"])
    item = make_inventory(service_db, company_id, "Impeller", qty=5)
    job = _job(client, owner)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(item), "quantity": 1, "job_id": job},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403


def test_stock_can_still_be_used_without_a_job(client, service_db):
    """The job link is optional; the original behaviour is unchanged."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    item = make_inventory(service_db, company_id, "Impeller", qty=5)

    resp = client.post(
        "/api/v1/inventory/use",
        json={"item_id": str(item), "quantity": 1},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["remaining_on_hand"] == 4
