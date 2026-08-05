"""Storage billing: a slip reservation generates a `job_line_items` row
(kind='storage') which then freezes onto an invoice through the exact same
`app.services.invoices` machinery job labor/part/fee lines use (Phase 15
reuses Phase 3's invoicing rather than a parallel system).
"""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer


def _slip(client, owner, daily_rate="40.00", **fields):
    body = {"identifier": "A-1", "slip_type": "wet_slip", "daily_rate": daily_rate, **fields}
    resp = client.post("/api/v1/slips", json=body, headers=auth_headers(owner))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _reservation(client, owner, slip_id, customer_id, start="2026-05-01", end="2026-05-05"):
    resp = client.post(
        "/api/v1/slip-reservations",
        json={
            "slip_id": slip_id, "customer_id": customer_id,
            "start_date": start, "end_date": end,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_generate_storage_charge_defaults_to_nights_times_daily_rate(client):
    owner = signup(client)
    slip_id = _slip(client, owner, daily_rate="40.00")
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id, start="2026-05-01", end="2026-05-05")

    resp = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge", json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()
    assert line["kind"] == "storage"
    assert line["slip_reservation_id"] == rid
    # 4 nights (May 1 -> May 5) at $40/night = $160.00
    assert line["quantity"] == "4.00" or float(line["quantity"]) == 4.0
    assert float(line["unit_price"]) == 40.0


def test_generate_storage_charge_accepts_rate_and_quantity_override(client):
    owner = signup(client)
    slip_id = _slip(client, owner, daily_rate="40.00", monthly_rate="500.00")
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id, start="2026-05-01", end="2026-06-01")

    resp = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge",
        json={"rate": "500.00", "quantity": "1", "description": "May monthly rent"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()
    assert float(line["unit_price"]) == 500.0
    assert float(line["quantity"]) == 1.0
    assert line["description"] == "May monthly rent"


def test_cannot_generate_a_second_storage_charge_for_the_same_reservation(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id)

    first = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge", json={},
        headers=auth_headers(owner),
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge", json={},
        headers=auth_headers(owner),
    )
    assert second.status_code == 409, second.text


def test_generate_invoice_from_reservation_freezes_the_storage_line(client):
    owner = signup(client)
    slip_id = _slip(client, owner, daily_rate="40.00")
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id, start="2026-05-01", end="2026-05-05")

    charge = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge", json={},
        headers=auth_headers(owner),
    ).json()
    assert charge["invoice_id"] is None

    resp = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-invoice", json={"tax_rate": "0.07"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    invoice = resp.json()

    # subtotal = 4 nights * $40.00 = $160.00; tax = round(160*0.07,2) = 11.20
    assert invoice["subtotal"] == "160.00"
    assert invoice["tax_total"] == "11.20"
    assert invoice["total"] == "171.20"
    assert invoice["customer_id"] == customer_id
    assert len(invoice["line_items"]) == 1
    assert invoice["line_items"][0]["id"] == charge["id"]


def test_generate_invoice_without_a_storage_charge_first_is_a_conflict(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id)

    resp = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-invoice", json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409, resp.text


def test_generate_invoice_for_unknown_reservation_is_404(client):
    owner = signup(client)
    resp = client.post(
        f"/api/v1/slip-reservations/{uuid.uuid4()}/generate-invoice", json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


def test_a_technician_cannot_generate_a_storage_charge(client):
    from tests.conftest import invite

    owner = signup(client)
    tech = invite(client, owner, "technician")
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id)

    resp = client.post(
        f"/api/v1/slip-reservations/{rid}/generate-storage-charge", json={},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403
