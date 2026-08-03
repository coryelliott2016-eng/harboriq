"""Creating an invoice from a job's uninvoiced line items."""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _add_line(client, actor, job_id, **fields):
    body = {"kind": "labor", "description": "Diagnosis", "quantity": "1.00", **fields}
    resp = client.post(
        f"/api/v1/jobs/{job_id}/line-items", json=body, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_invoice(client, actor, job_id, **fields):
    return client.post(
        "/api/v1/invoices", json={"job_id": job_id, **fields}, headers=auth_headers(actor)
    )


def test_invoice_computes_subtotal_tax_and_total_from_real_numeric_math(client):
    owner = signup(client)
    job = _job(client, owner)
    _add_line(client, owner, job, description="Labor", quantity="2.00", unit_price="95.00")
    _add_line(
        client, owner, job, kind="fee", description="Shop supplies",
        quantity="1.00", unit_price="15.00",
    )

    resp = _create_invoice(client, owner, job, tax_rate="0.07")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # subtotal = 2*95 + 1*15 = 205.00; both lines taxable by default so
    # tax_total = round(205.00 * 0.07, 2) = 14.35; total = 219.35.
    assert body["subtotal"] == "205.00"
    assert body["tax_total"] == "14.35"
    assert body["total"] == "219.35"
    assert body["status"] == "draft"
    assert body["amount_paid"] == "0.00"
    assert body["balance_due"] == "219.35"
    assert len(body["line_items"]) == 2


def test_a_non_taxable_line_is_excluded_from_tax_total(client):
    owner = signup(client)
    job = _job(client, owner)
    _add_line(
        client, owner, job, description="Labor", quantity="1.00", unit_price="100.00",
        taxable=False,
    )

    resp = _create_invoice(client, owner, job, tax_rate="0.10")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["subtotal"] == "100.00"
    assert body["tax_total"] == "0.00"
    assert body["total"] == "100.00"


def test_invoiced_lines_are_frozen_onto_the_invoice(client):
    owner = signup(client)
    job = _job(client, owner)
    line = _add_line(client, owner, job, quantity="1.00", unit_price="50.00")

    resp = _create_invoice(client, owner, job)
    assert resp.status_code == 201, resp.text
    invoice_id = resp.json()["id"]

    lines = client.get(
        f"/api/v1/jobs/{job}/line-items", headers=auth_headers(owner)
    ).json()
    assert lines[0]["id"] == line["id"]
    assert lines[0]["invoice_id"] == invoice_id
    assert lines[0]["invoiced_at"] is not None


def test_a_job_with_nothing_uninvoiced_cannot_be_invoiced_again(client):
    owner = signup(client)
    job = _job(client, owner)
    _add_line(client, owner, job, quantity="1.00", unit_price="50.00")

    first = _create_invoice(client, owner, job)
    assert first.status_code == 201, first.text

    second = _create_invoice(client, owner, job)
    assert second.status_code == 409, second.text


def test_a_job_with_no_lines_at_all_cannot_be_invoiced(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _create_invoice(client, owner, job)
    assert resp.status_code == 409, resp.text


def test_an_unknown_job_is_a_404(client):
    owner = signup(client)
    resp = _create_invoice(client, owner, str(uuid.uuid4()))
    assert resp.status_code == 404


def test_a_technician_cannot_create_an_invoice(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)
    _add_line(client, owner, job, quantity="1.00", unit_price="50.00")

    resp = _create_invoice(client, tech, job)
    assert resp.status_code == 403


def test_office_role_can_create_an_invoice(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    job = _job(client, owner)
    _add_line(client, owner, job, quantity="1.00", unit_price="50.00")

    resp = _create_invoice(client, office, job)
    assert resp.status_code == 201, resp.text
