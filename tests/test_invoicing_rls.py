"""Tenant isolation for invoicing tables, mirroring test_crm_rls.py.

Same two guarantees as the CRM tables:
* RLS — a session scoped to tenant A cannot read/write tenant B's estimates,
  invoices or payments, even with no WHERE clause.
* Tenant-safe composite foreign keys (added in migration 0004) — an internal
  FK-check query bypasses RLS, so without `(company_id, x_id) REFERENCES
  y(company_id, id)`, tenant A could still point an invoice at a row it
  cannot even see.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.db.tenant import tenant_context
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _customer(db, company_id, last_name="Halyard") -> uuid.UUID:
    row = db.execute(
        text("INSERT INTO customers (company_id, last_name) VALUES (:cid, :name) RETURNING id"),
        {"cid": company_id, "name": last_name},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def _job(db, company_id, customer_id, title="Winterize") -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO jobs (company_id, customer_id, title) VALUES (:cid, :cust, :title) "
            "RETURNING id"
        ),
        {"cid": company_id, "cust": customer_id, "title": title},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def _invoice(db, company_id, customer_id=None, status="draft", total="100.00") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO invoices (company_id, customer_id, status, total, balance_due)
            VALUES (:cid, :cust, :status, :total, :total)
            RETURNING id
            """
        ),
        {"cid": company_id, "cust": customer_id, "status": status, "total": total},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", ["invoices", "payments"])
def test_an_unfiltered_select_sees_only_its_own_tenant(
    app_db, service_db, company_a, company_b, table
):
    for company in (company_a, company_b):
        customer = _customer(service_db, company)
        invoice = _invoice(service_db, company, customer)
        service_db.execute(
            text(
                """
                INSERT INTO payments (company_id, invoice_id, amount, status)
                VALUES (:cid, :inv, 10, 'succeeded')
                """
            ),
            {"cid": company, "inv": invoice},
        )
    service_db.commit()

    with tenant_context(app_db, company_a):
        rows = app_db.execute(text(f"SELECT company_id FROM {table}")).all()

    assert rows, "setup produced no rows, so this test proves nothing"
    assert {uuid.UUID(str(row[0])) for row in rows} == {company_a}


def test_another_tenants_invoice_id_simply_does_not_exist(
    app_db, service_db, company_a, company_b
):
    theirs = _invoice(service_db, company_b)

    with tenant_context(app_db, company_a):
        row = app_db.execute(
            text("SELECT id FROM invoices WHERE id = :id"), {"id": theirs}
        ).first()
    assert row is None


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
def test_a_tenant_cannot_insert_an_invoice_for_another_company(
    app_db, company_a, company_b
):
    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                "INSERT INTO invoices (company_id, status, total, balance_due) "
                "VALUES (:cid, 'draft', 10, 10)"
            ),
            {"cid": company_b},
        )
    app_db.rollback()


def test_a_tenant_cannot_update_another_tenants_invoice(
    app_db, service_db, company_a, company_b
):
    theirs = _invoice(service_db, company_b)

    with tenant_context(app_db, company_a):
        result = app_db.execute(
            text("UPDATE invoices SET status = 'void' WHERE id = :id"), {"id": theirs}
        )
        assert result.rowcount == 0
    app_db.rollback()


# ---------------------------------------------------------------------------
# tenant-safe foreign keys (migration 0004)
# ---------------------------------------------------------------------------
def test_an_invoice_cannot_reference_an_invisible_customer(
    app_db, service_db, company_a, company_b
):
    theirs = _customer(service_db, company_b)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                "INSERT INTO invoices (company_id, customer_id, status, total, balance_due) "
                "VALUES (:cid, :cust, 'draft', 10, 10)"
            ),
            {"cid": company_a, "cust": theirs},
        )
    app_db.rollback()


def test_an_invoice_cannot_reference_another_tenants_estimate(
    app_db, service_db, company_a, company_b
):
    their_estimate = service_db.execute(
        text(
            "INSERT INTO estimates (company_id, status, total, balance_due) "
            "VALUES (:cid, 'sent', 10, 10) RETURNING id"
        ),
        {"cid": company_b},
    ).first()[0]
    service_db.commit()

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                "INSERT INTO invoices (company_id, estimate_id, status, total, balance_due) "
                "VALUES (:cid, :est, 'draft', 10, 10)"
            ),
            {"cid": company_a, "est": their_estimate},
        )
    app_db.rollback()


def test_an_estimate_cannot_reference_another_tenants_job(
    app_db, service_db, company_a, company_b
):
    my_customer = _customer(service_db, company_a)
    their_customer = _customer(service_db, company_b)
    their_job = _job(service_db, company_b, their_customer)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                "INSERT INTO estimates (company_id, customer_id, job_id, status, total, balance_due) "
                "VALUES (:cid, :cust, :job, 'draft', 10, 10)"
            ),
            {"cid": company_a, "cust": my_customer, "job": their_job},
        )
    app_db.rollback()


def test_a_payment_cannot_attach_to_another_tenants_invoice(
    app_db, service_db, company_a, company_b
):
    their_invoice = _invoice(service_db, company_b)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                "INSERT INTO payments (company_id, invoice_id, amount, status) "
                "VALUES (:cid, :inv, 10, 'succeeded')"
            ),
            {"cid": company_a, "inv": their_invoice},
        )
    app_db.rollback()


def test_a_job_line_item_cannot_be_invoiced_to_another_tenants_invoice(
    app_db, service_db, company_a, company_b
):
    my_customer = _customer(service_db, company_a)
    my_job = _job(service_db, company_a, my_customer)
    line = service_db.execute(
        text(
            "INSERT INTO job_line_items (company_id, job_id, kind, description, quantity, unit_price) "
            "VALUES (:cid, :job, 'labor', 'Diagnosis', 1, 95) RETURNING id"
        ),
        {"cid": company_a, "job": my_job},
    ).first()[0]
    service_db.commit()

    their_invoice = _invoice(service_db, company_b)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text("UPDATE job_line_items SET invoice_id = :inv WHERE id = :id"),
            {"inv": their_invoice, "id": line},
        )
    app_db.rollback()


# ---------------------------------------------------------------------------
# the same guarantees through the API
# ---------------------------------------------------------------------------
def test_the_api_hides_another_tenants_invoice(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")

    customer = make_customer(client, b, "Theirs")
    job = make_job(client, b, customer).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": "50.00"},
        headers=auth_headers(b),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(b)
    ).json()

    assert client.get(
        f"/api/v1/invoices/{invoice['id']}", headers=auth_headers(a)
    ).status_code == 404
    assert client.get("/api/v1/invoices", headers=auth_headers(a)).json() == []


def test_the_api_refuses_to_mutate_another_tenants_invoice(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")

    customer = make_customer(client, b, "Theirs")
    job = make_job(client, b, customer).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": "50.00"},
        headers=auth_headers(b),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(b)
    ).json()

    assert client.post(
        f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(a)
    ).status_code == 404
    assert client.post(
        f"/api/v1/invoices/{invoice['id']}/void", headers=auth_headers(a)
    ).status_code == 404
