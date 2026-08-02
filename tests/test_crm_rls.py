"""Tenant isolation for the CRM tables, at the database and at the API.

Two distinct guarantees are checked here:

* RLS — a session scoped to tenant A cannot read or write tenant B's
  customers, vessels, jobs or line items, even with no WHERE clause.
* Tenant-safe foreign keys — a plain `REFERENCES customers(id)` is validated by
  an internal system query that RLS does NOT apply to, so without the composite
  `(company_id, id)` keys added in migration 0003, tenant A could point a
  vessel or job at a row it cannot even see. Those tests are the reason the
  composite keys exist.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.db.tenant import tenant_context
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job, make_vessel


def _customer(db, company_id, last_name="Halyard") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO customers (company_id, last_name)
            VALUES (:cid, :name) RETURNING id
            """
        ),
        {"cid": company_id, "name": last_name},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def _vessel(db, company_id, customer_id, name="Second Wind") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO vessels (company_id, customer_id, name)
            VALUES (:cid, :cust, :name) RETURNING id
            """
        ),
        {"cid": company_id, "cust": customer_id, "name": name},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


def _job(db, company_id, customer_id, title="Winterize") -> uuid.UUID:
    row = db.execute(
        text(
            """
            INSERT INTO jobs (company_id, customer_id, title)
            VALUES (:cid, :cust, :title) RETURNING id
            """
        ),
        {"cid": company_id, "cust": customer_id, "title": title},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0]))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", ["customers", "vessels", "jobs", "job_line_items"])
def test_an_unfiltered_select_sees_only_its_own_tenant(
    app_db, service_db, company_a, company_b, table
):
    for company in (company_a, company_b):
        customer = _customer(service_db, company)
        _vessel(service_db, company, customer)
        job = _job(service_db, company, customer)
        service_db.execute(
            text(
                """
                INSERT INTO job_line_items
                    (company_id, job_id, kind, description, quantity, unit_price)
                VALUES (:cid, :job, 'labor', 'Diagnosis', 1, 95)
                """
            ),
            {"cid": company, "job": job},
        )
    service_db.commit()

    with tenant_context(app_db, company_a):
        rows = app_db.execute(text(f"SELECT company_id FROM {table}")).all()

    assert rows, "setup produced no rows, so this test proves nothing"
    assert {uuid.UUID(str(row[0])) for row in rows} == {company_a}


def test_another_tenants_id_simply_does_not_exist(
    app_db, service_db, company_a, company_b
):
    theirs = _customer(service_db, company_b)

    with tenant_context(app_db, company_a):
        row = app_db.execute(
            text("SELECT id FROM customers WHERE id = :id"), {"id": theirs}
        ).first()
    assert row is None


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
def test_a_tenant_cannot_insert_a_customer_for_another_company(
    app_db, company_a, company_b
):
    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                """
                INSERT INTO customers (company_id, last_name)
                VALUES (:cid, 'Stolen')
                """
            ),
            {"cid": company_b},
        )
    app_db.rollback()


def test_a_tenant_cannot_update_another_tenants_customer(
    app_db, service_db, company_a, company_b
):
    theirs = _customer(service_db, company_b, "Theirs")

    with tenant_context(app_db, company_a):
        result = app_db.execute(
            text("UPDATE customers SET last_name = 'Hijacked' WHERE id = :id"),
            {"id": theirs},
        )
        assert result.rowcount == 0
    app_db.rollback()


def test_a_tenant_cannot_delete_another_tenants_job(
    app_db, service_db, company_a, company_b
):
    customer = _customer(service_db, company_b)
    theirs = _job(service_db, company_b, customer)

    with tenant_context(app_db, company_a):
        result = app_db.execute(
            text("DELETE FROM jobs WHERE id = :id"), {"id": theirs}
        )
        assert result.rowcount == 0
    app_db.rollback()


# ---------------------------------------------------------------------------
# tenant-safe foreign keys
# ---------------------------------------------------------------------------
def test_a_vessel_cannot_reference_an_invisible_customer(
    app_db, service_db, company_a, company_b
):
    """FK checks bypass RLS, so only a composite key stops this."""
    theirs = _customer(service_db, company_b)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                """
                INSERT INTO vessels (company_id, customer_id, name)
                VALUES (:cid, :cust, 'Poached')
                """
            ),
            {"cid": company_a, "cust": theirs},
        )
    app_db.rollback()


def test_a_job_cannot_reference_another_tenants_vessel(
    app_db, service_db, company_a, company_b
):
    mine = _customer(service_db, company_a)
    their_customer = _customer(service_db, company_b)
    their_vessel = _vessel(service_db, company_b, their_customer)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                """
                INSERT INTO jobs (company_id, customer_id, vessel_id, title)
                VALUES (:cid, :cust, :vessel, 'Poached')
                """
            ),
            {"cid": company_a, "cust": mine, "vessel": their_vessel},
        )
    app_db.rollback()


def test_a_job_cannot_be_dispatched_to_another_tenants_user(
    app_db, service_db, company_a, company_b
):
    mine = _customer(service_db, company_a)
    outsider = service_db.execute(
        text(
            """
            INSERT INTO users (company_id, email, password_hash, role)
            VALUES (:cid, :email, 'x', 'technician')
            RETURNING id
            """
        ),
        {"cid": company_b, "email": f"outsider-{uuid.uuid4().hex[:8]}@example.com"},
    ).first()
    service_db.commit()

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                """
                INSERT INTO jobs (company_id, customer_id, technician_id, title)
                VALUES (:cid, :cust, :tech, 'Poached')
                """
            ),
            {"cid": company_a, "cust": mine, "tech": outsider[0]},
        )
    app_db.rollback()


def test_a_line_item_cannot_attach_to_another_tenants_job(
    app_db, service_db, company_a, company_b
):
    their_customer = _customer(service_db, company_b)
    their_job = _job(service_db, company_b, their_customer)

    with tenant_context(app_db, company_a), pytest.raises(DatabaseError):
        app_db.execute(
            text(
                """
                INSERT INTO job_line_items
                    (company_id, job_id, kind, description, quantity, unit_price)
                VALUES (:cid, :job, 'labor', 'Poached', 1, 95)
                """
            ),
            {"cid": company_a, "job": their_job},
        )
    app_db.rollback()


# ---------------------------------------------------------------------------
# the same guarantees through the API
# ---------------------------------------------------------------------------
def test_the_api_hides_another_tenants_records(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")

    customer = make_customer(client, b, "Theirs")
    vessel = make_vessel(client, b, customer)
    job = make_job(client, b, customer).json()["id"]

    for path in (
        f"/api/v1/customers/{customer}",
        f"/api/v1/vessels/{vessel}",
        f"/api/v1/jobs/{job}",
    ):
        assert client.get(path, headers=auth_headers(a)).status_code == 404, path

    assert client.get("/api/v1/customers", headers=auth_headers(a)).json() == []
    assert client.get("/api/v1/vessels", headers=auth_headers(a)).json() == []
    assert client.get("/api/v1/jobs", headers=auth_headers(a)).json() == []


def test_the_api_refuses_to_mutate_another_tenants_records(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    customer = make_customer(client, b, "Theirs")
    job = make_job(client, b, customer).json()["id"]

    assert client.patch(
        f"/api/v1/customers/{customer}",
        json={"city": "Hijacked"},
        headers=auth_headers(a),
    ).status_code == 404
    assert client.delete(
        f"/api/v1/jobs/{job}", headers=auth_headers(a)
    ).status_code == 404
    assert client.post(
        f"/api/v1/jobs/{job}/status",
        json={"status": "in_progress"},
        headers=auth_headers(a),
    ).status_code == 404
