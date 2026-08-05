"""P&L report (Phase 14): revenue/cost/labor computation against seeded
invoices/refunds/POs/time-entries, monthly grouping, "unavailable" (not
zero) labor cost when a technician has no `hourly_rate` set, tenant
isolation.

Methodology under test (see app/services/reports.py's module docstring):
  revenue    = succeeded `payments.amount` in-period minus `refunds.amount`
               in-period (cash collected, not accrual-invoiced value).
  parts cost = purchase_order_line_items.quantity_received * unit_cost for
               POs whose received_at falls in-period.
  labor cost = closed job_time_entries duration * users.hourly_rate; NULL
               hourly_rate -> "unavailable", not $0.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.services import stripe_billing
from tests.conftest import (
    auth_headers,
    invite,
    make_purchase_order,
    make_vendor,
    signup,
)
from tests.test_crm_jobs import make_customer, make_job


def _mock_refund(monkeypatch, refund_id="re_test_pnl"):
    monkeypatch.setattr(
        stripe_billing, "create_refund", lambda **kwargs: {"id": refund_id}
    )


def _pay_invoice(client, service_db, actor, customer_id, unit_price, paid_at=None):
    """Create + send + pay (webhook) an invoice; optionally backdate the
    resulting `payments.created_at` so P&L monthly grouping is testable."""
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

    session_id = f"cs_test_pnl_{uuid.uuid4().hex[:8]}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()

    from app.services import invoices as invoices_service

    company_id = uuid.UUID(actor["user"]["company_id"])
    cents = int(Decimal(unit_price) * 100)
    invoices_service.mark_paid_from_webhook(
        service_db, company_id, stripe_checkout_session_id=session_id, amount_paid_cents=cents
    )
    service_db.commit()

    if paid_at is not None:
        service_db.execute(
            text("UPDATE payments SET created_at = :ts WHERE invoice_id = :iid"),
            {"ts": paid_at, "iid": invoice["id"]},
        )
        service_db.commit()
    return invoice


def _received_po(service_db, company_id, vendor_id, created_by, qty, unit_cost, received_at):
    po_id = make_purchase_order(
        service_db, company_id, vendor_id, created_by,
        [(_seed_part(service_db, company_id), qty, unit_cost)],
    )
    service_db.execute(
        text(
            """
            UPDATE purchase_order_line_items
               SET quantity_received = :qty
             WHERE purchase_order_id = :po_id
            """
        ),
        {"qty": qty, "po_id": po_id},
    )
    service_db.execute(
        text(
            "UPDATE purchase_orders SET status = 'received', received_at = :ts WHERE id = :id"
        ),
        {"ts": received_at, "id": po_id},
    )
    service_db.commit()
    return po_id


def _seed_part(service_db, company_id, name=None):
    row = service_db.execute(
        text(
            """
            INSERT INTO inventory_items (company_id, name, sku, unit_cost, retail_price, quantity_on_hand)
            VALUES (:cid, :name, :sku, 0, 0, 100)
            RETURNING id
            """
        ),
        {"cid": company_id, "name": name or f"Part {uuid.uuid4().hex[:6]}", "sku": uuid.uuid4().hex[:10]},
    ).first()
    service_db.commit()
    return uuid.UUID(str(row[0]))


def _time_entry(service_db, company_id, job_id, technician_id, clocked_in_at, hours):
    clocked_out_at = clocked_in_at + timedelta(hours=hours)
    service_db.execute(
        text(
            """
            INSERT INTO job_time_entries
                (company_id, job_id, technician_id, clocked_in_at, clocked_out_at)
            VALUES (:cid, :job_id, :tech_id, :in_at, :out_at)
            """
        ),
        {
            "cid": company_id, "job_id": job_id, "tech_id": technician_id,
            "in_at": clocked_in_at, "out_at": clocked_out_at,
        },
    )
    service_db.commit()


def _set_hourly_rate(service_db, user_id, rate):
    service_db.execute(
        text("UPDATE users SET hourly_rate = :rate WHERE id = :id"), {"rate": rate, "id": user_id}
    )
    service_db.commit()


def test_revenue_is_cash_collected_minus_refunds_in_period(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "100.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    assert Decimal(totals["revenue"]) == Decimal("100.00")
    assert Decimal(totals["net_revenue"]) == Decimal("100.00")


def test_refunds_reduce_revenue_in_the_period_they_occur(client, service_db, monkeypatch):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    now = datetime.now(timezone.utc)
    invoice = _pay_invoice(client, service_db, owner, customer_id, "100.00", paid_at=now)
    _mock_refund(monkeypatch)

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", json={"amount": "40.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    totals = resp.json()["totals"]
    assert Decimal(totals["revenue"]) == Decimal("100.00")
    assert Decimal(totals["refunds"]) == Decimal("40.00")
    assert Decimal(totals["net_revenue"]) == Decimal("60.00")


def test_parts_cost_from_received_purchase_order_line_items(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    vendor_id = make_vendor(service_db, company_id)
    now = datetime.now(timezone.utc)

    _received_po(service_db, company_id, vendor_id, owner_id, qty=10, unit_cost="5.00", received_at=now)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    assert Decimal(totals["parts_cost"]) == Decimal("50.00")


def test_labor_cost_computed_from_rate_and_duration(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    tech = invite(client, owner, "technician")
    tech_id = uuid.UUID(tech["user"]["id"])
    _set_hourly_rate(service_db, tech_id, "25.00")

    customer_id = make_customer(client, owner)
    job_id = make_job(client, owner, customer_id).json()["id"]
    now = datetime.now(timezone.utc)
    _time_entry(service_db, company_id, job_id, tech_id, now, hours=4)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    assert Decimal(totals["labor_cost"]) == Decimal("100.00")
    assert totals["labor_cost_unavailable"] is False


def test_technician_with_no_hourly_rate_shows_unavailable_not_zero(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    tech = invite(client, owner, "technician")
    tech_id = uuid.UUID(tech["user"]["id"])
    # Deliberately never set hourly_rate.

    customer_id = make_customer(client, owner)
    job_id = make_job(client, owner, customer_id).json()["id"]
    now = datetime.now(timezone.utc)
    _time_entry(service_db, company_id, job_id, tech_id, now, hours=3)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    # Must be flagged unavailable, and the labor_cost figure must NOT
    # silently include this technician's hours as $0 -- it stays $0 in the
    # sum (nothing else contributed), but the flag says the number is known
    # incomplete, and the technician is named so an operator can act on it.
    assert totals["labor_cost_unavailable"] is True
    assert tech["user"]["full_name"] in totals["unrated_technicians"] or str(tech_id) in totals[
        "unrated_technicians"
    ]


def test_open_time_entries_are_excluded_from_labor_cost(client, service_db):
    """An entry with no clocked_out_at yet has no final duration -- must not
    be counted (and must not crash trying to subtract None)."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    tech = invite(client, owner, "technician")
    tech_id = uuid.UUID(tech["user"]["id"])
    _set_hourly_rate(service_db, tech_id, "50.00")

    customer_id = make_customer(client, owner)
    job_id = make_job(client, owner, customer_id).json()["id"]
    now = datetime.now(timezone.utc)
    service_db.execute(
        text(
            """
            INSERT INTO job_time_entries (company_id, job_id, technician_id, clocked_in_at)
            VALUES (:cid, :job_id, :tech_id, :in_at)
            """
        ),
        {"cid": company_id, "job_id": job_id, "tech_id": tech_id, "in_at": now},
    )
    service_db.commit()

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    assert Decimal(totals["labor_cost"]) == Decimal("0")
    assert totals["labor_cost_unavailable"] is False


def test_net_is_revenue_minus_parts_minus_labor(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    customer_id = make_customer(client, owner)
    vendor_id = make_vendor(service_db, company_id)
    tech = invite(client, owner, "technician")
    tech_id = uuid.UUID(tech["user"]["id"])
    _set_hourly_rate(service_db, tech_id, "20.00")

    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "500.00", paid_at=now)
    _received_po(service_db, company_id, vendor_id, owner_id, qty=5, unit_cost="10.00", received_at=now)
    job_id = make_job(client, owner, customer_id).json()["id"]
    _time_entry(service_db, company_id, job_id, tech_id, now, hours=2)  # $40 labor

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    totals = resp.json()["totals"]
    # revenue 500 - parts (5*10=50) - labor (2*20=40) = 410
    assert Decimal(totals["net"]) == Decimal("410.00")


def test_monthly_grouping_buckets_by_month(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)

    month1 = datetime(2025, 1, 15, tzinfo=timezone.utc)
    month2 = datetime(2025, 2, 15, tzinfo=timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "100.00", paid_at=month1)
    _pay_invoice(client, service_db, owner, customer_id, "200.00", paid_at=month2)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": "2025-01-01T00:00:00+00:00",
            "end_date": "2025-03-01T00:00:00+00:00",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    months = {m["month"]: m for m in resp.json()["months"]}
    assert Decimal(months["2025-01"]["revenue"]) == Decimal("100.00")
    assert Decimal(months["2025-02"]["revenue"]) == Decimal("200.00")


def test_report_is_scoped_to_its_own_tenant(client, service_db):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    customer_a = make_customer(client, owner_a)
    customer_b = make_customer(client, owner_b)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner_a, customer_a, "10.00", paid_at=now)
    _pay_invoice(client, service_db, owner_b, customer_b, "999.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/pnl",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner_a),
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["revenue"]) == Decimal("10.00")


def test_a_technician_cannot_view_the_report(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get("/api/v1/reports/pnl", headers=auth_headers(tech))
    assert resp.status_code == 403


def test_defaults_to_a_broad_range_when_no_dates_given(client, service_db):
    """No start_date/end_date supplied -> defaults to epoch..now, so nothing
    silently 422s or returns an empty report for a reasonable "show me
    everything" call."""
    owner = signup(client)
    customer_id = make_customer(client, owner)
    _pay_invoice(client, service_db, owner, customer_id, "42.00", paid_at=datetime.now(timezone.utc))

    resp = client.get("/api/v1/reports/pnl", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["revenue"]) == Decimal("42.00")
