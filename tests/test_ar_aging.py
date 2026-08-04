"""AR aging report (Phase 8): bucketing logic against seeded data with known
due dates, grouped by customer, tenant isolation, role gating.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _invoice_due_in(client, service_db, actor, customer_id, days_from_now, unit_price="100.00"):
    job = make_job(client, actor, customer_id).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": unit_price},
        headers=auth_headers(actor),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(actor)
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(actor))

    due_date = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    service_db.execute(
        text("UPDATE invoices SET due_date = :d WHERE id = :id"),
        {"d": due_date, "id": invoice["id"]},
    )
    service_db.commit()
    return invoice


def test_buckets_invoices_by_days_overdue(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner, last_name="Current")
    _invoice_due_in(client, service_db, owner, customer_id, days_from_now=10, unit_price="10.00")

    customer_1_30 = make_customer(client, owner, last_name="OneToThirty")
    _invoice_due_in(client, service_db, owner, customer_1_30, days_from_now=-15, unit_price="20.00")

    customer_31_60 = make_customer(client, owner, last_name="ThirtyOneToSixty")
    _invoice_due_in(client, service_db, owner, customer_31_60, days_from_now=-45, unit_price="30.00")

    customer_61_90 = make_customer(client, owner, last_name="SixtyOneToNinety")
    _invoice_due_in(client, service_db, owner, customer_61_90, days_from_now=-75, unit_price="40.00")

    customer_90_plus = make_customer(client, owner, last_name="NinetyPlus")
    _invoice_due_in(client, service_db, owner, customer_90_plus, days_from_now=-120, unit_price="50.00")

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    totals = body["bucket_totals"]
    assert totals["current"] == "10.00"
    assert totals["days_1_30"] == "20.00"
    assert totals["days_31_60"] == "30.00"
    assert totals["days_61_90"] == "40.00"
    assert totals["days_90_plus"] == "50.00"
    assert body["grand_total"] == "150.00"
    assert len(body["customers"]) == 5


def test_boundary_days_land_in_the_correct_bucket(client, service_db):
    owner = signup(client)
    # Exactly on the due date (0 days overdue) -> current.
    c0 = make_customer(client, owner, last_name="Zero")
    _invoice_due_in(client, service_db, owner, c0, days_from_now=0, unit_price="1.00")

    # 30 days overdue -> still 1-30, not 31-60.
    c30 = make_customer(client, owner, last_name="Thirty")
    _invoice_due_in(client, service_db, owner, c30, days_from_now=-30, unit_price="2.00")

    # 31 days overdue -> 31-60.
    c31 = make_customer(client, owner, last_name="ThirtyOne")
    _invoice_due_in(client, service_db, owner, c31, days_from_now=-31, unit_price="4.00")

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    totals = resp.json()["bucket_totals"]
    assert totals["current"] == "1.00"
    assert totals["days_1_30"] == "2.00"
    assert totals["days_31_60"] == "4.00"


def test_invoices_with_no_due_date_are_treated_as_current(client):
    """A draft/never-sent invoice has no due_date yet -- there is no date to
    be overdue against, so it must not silently disappear or explode."""
    owner = signup(client)
    customer_id = make_customer(client, owner)
    job = make_job(client, owner, customer_id).json()["id"]
    client.post(
        f"/api/v1/jobs/{job}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": "75.00"},
        headers=auth_headers(owner),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job}, headers=auth_headers(owner)
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=auth_headers(owner))

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["grand_total"] == "75.00"


def test_paid_invoices_do_not_appear_in_the_report(client, service_db):
    from app.services import invoices as invoices_service
    import uuid as uuid_mod

    owner = signup(client)
    customer_id = make_customer(client, owner)
    invoice = _invoice_due_in(client, service_db, owner, customer_id, days_from_now=-10, unit_price="99.00")

    company_id = uuid_mod.UUID(owner["user"]["company_id"])
    session_id = f"cs_test_aging_{uuid_mod.uuid4().hex[:6]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()
    invoices_service.mark_paid_from_webhook(
        service_db, company_id, stripe_checkout_session_id=session_id, amount_paid_cents=9900
    )
    service_db.commit()

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    # An empty report's Decimal(0) accumulator serializes as "0", not
    # "0.00" (no quantized DB value ever flowed into it) -- Decimal("0") ==
    # Decimal("0.00") numerically, so compare as Decimal rather than pinning
    # the exact string representation.
    from decimal import Decimal

    assert Decimal(resp.json()["grand_total"]) == Decimal("0")
    assert resp.json()["customers"] == []


def test_grouped_by_customer_with_multiple_invoices(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner, last_name="Repeat")
    _invoice_due_in(client, service_db, owner, customer_id, days_from_now=-5, unit_price="10.00")
    _invoice_due_in(client, service_db, owner, customer_id, days_from_now=-40, unit_price="20.00")

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    customers = resp.json()["customers"]
    assert len(customers) == 1
    entry = customers[0]
    assert entry["invoice_count"] == 2
    assert entry["total"] == "30.00"
    assert entry["buckets"]["days_1_30"] == "10.00"
    assert entry["buckets"]["days_31_60"] == "20.00"


def test_report_is_scoped_to_its_own_tenant(client, service_db):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    customer_a = make_customer(client, owner_a)
    customer_b = make_customer(client, owner_b)
    _invoice_due_in(client, service_db, owner_a, customer_a, days_from_now=-5, unit_price="10.00")
    _invoice_due_in(client, service_db, owner_b, customer_b, days_from_now=-5, unit_price="999.00")

    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(owner_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["grand_total"] == "10.00"


def test_a_technician_cannot_view_the_report(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(tech))
    assert resp.status_code == 403


def test_office_role_can_view_the_report(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    resp = client.get("/api/v1/reports/ar-aging", headers=auth_headers(office))
    assert resp.status_code == 200
