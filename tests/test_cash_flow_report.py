"""Cash flow report (Phase 14): cash-in/cash-out bucketing, tenant
isolation. Cash out is explicitly "cost incurred" (PO received line items),
not a recorded vendor cash-payment date -- see the report's
`cost_incurred_caveat` field and app/services/reports.py's module docstring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.conftest import auth_headers, invite, make_vendor, signup
from tests.test_crm_jobs import make_customer
from tests.test_pnl_report import _mock_refund, _pay_invoice, _received_po


def test_cash_in_reflects_succeeded_payments(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "150.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/cash-flow",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    totals = resp.json()["totals"]
    assert Decimal(totals["cash_in"]) == Decimal("150.00")


def test_cash_out_is_cost_incurred_from_received_pos(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    vendor_id = make_vendor(service_db, company_id)
    now = datetime.now(timezone.utc)
    _received_po(service_db, company_id, vendor_id, owner_id, qty=4, unit_cost="15.00", received_at=now)

    resp = client.get(
        "/api/v1/reports/cash-flow",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["totals"]["cost_incurred"]) == Decimal("60.00")
    # Must be explicit that this is not literally a cash-paid date.
    assert "not" in body["cost_incurred_caveat"].lower()
    assert "cash" in body["cost_incurred_caveat"].lower()


def test_net_cash_is_in_minus_refunds_minus_cost_incurred(client, service_db, monkeypatch):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    customer_id = make_customer(client, owner)
    vendor_id = make_vendor(service_db, company_id)
    now = datetime.now(timezone.utc)

    invoice = _pay_invoice(client, service_db, owner, customer_id, "300.00", paid_at=now)
    _mock_refund(monkeypatch)
    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/refund", json={"amount": "50.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    _received_po(service_db, company_id, vendor_id, owner_id, qty=2, unit_cost="25.00", received_at=now)

    resp = client.get(
        "/api/v1/reports/cash-flow",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    totals = resp.json()["totals"]
    # 300 in - 50 refunded - 50 cost incurred = 200
    assert Decimal(totals["net_cash"]) == Decimal("200.00")


def test_monthly_grouping(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    month1 = datetime(2025, 5, 10, tzinfo=timezone.utc)
    month2 = datetime(2025, 6, 10, tzinfo=timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "10.00", paid_at=month1)
    _pay_invoice(client, service_db, owner, customer_id, "20.00", paid_at=month2)

    resp = client.get(
        "/api/v1/reports/cash-flow",
        params={"start_date": "2025-05-01T00:00:00+00:00", "end_date": "2025-07-01T00:00:00+00:00"},
        headers=auth_headers(owner),
    )
    months = {m["month"]: m for m in resp.json()["months"]}
    assert Decimal(months["2025-05"]["cash_in"]) == Decimal("10.00")
    assert Decimal(months["2025-06"]["cash_in"]) == Decimal("20.00")


def test_report_is_scoped_to_its_own_tenant(client, service_db):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    customer_a = make_customer(client, owner_a)
    customer_b = make_customer(client, owner_b)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner_a, customer_a, "10.00", paid_at=now)
    _pay_invoice(client, service_db, owner_b, customer_b, "999.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/cash-flow",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner_a),
    )
    assert Decimal(resp.json()["totals"]["cash_in"]) == Decimal("10.00")


def test_a_technician_cannot_view_the_report(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get("/api/v1/reports/cash-flow", headers=auth_headers(tech))
    assert resp.status_code == 403
