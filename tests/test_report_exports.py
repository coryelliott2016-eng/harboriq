"""CSV export endpoints (Phase 14): P&L, cash flow, AR aging, and the
QuickBooks Online-style 3-column transactions journal all produce valid,
correctly-formatted CSV with the expected headers/rows.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.conftest import auth_headers, invite, make_vendor, signup
from tests.test_crm_jobs import make_customer
from tests.test_pnl_report import _pay_invoice, _received_po


def _parse_csv(text_body: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text_body)))


def test_ar_aging_csv_export_has_expected_headers_and_rows(client, service_db):
    from tests.test_ar_aging import _invoice_due_in

    owner = signup(client)
    customer_id = make_customer(client, owner)
    _invoice_due_in(client, service_db, owner, customer_id, days_from_now=-10, unit_price="75.00")

    resp = client.get("/api/v1/reports/ar-aging/export.csv", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = _parse_csv(resp.text)
    header = rows[0]
    assert header == [
        "customer_name", "current", "days_1_30", "days_31_60", "days_61_90",
        "days_90_plus", "total", "invoice_count",
    ]
    # One customer row + one TOTAL row.
    assert len(rows) == 3
    assert rows[-1][0] == "TOTAL"
    assert Decimal(rows[-1][6]) == Decimal("75.00")


def test_pnl_csv_export_has_expected_headers_and_totals_row(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner, customer_id, "200.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/pnl/export.csv",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")

    rows = _parse_csv(resp.text)
    assert rows[0] == [
        "month", "revenue", "refunds", "net_revenue", "parts_cost",
        "labor_cost", "labor_cost_unavailable", "unrated_technicians", "net",
    ]
    assert rows[-1][0] == "TOTAL"
    assert Decimal(rows[-1][1]) == Decimal("200.00")


def test_cash_flow_csv_export_has_expected_headers(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    vendor_id = make_vendor(service_db, company_id)
    now = datetime.now(timezone.utc)
    _received_po(service_db, company_id, vendor_id, owner_id, qty=3, unit_cost="9.00", received_at=now)

    resp = client.get(
        "/api/v1/reports/cash-flow/export.csv",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    rows = _parse_csv(resp.text)
    assert rows[0] == ["month", "cash_in", "refunds_out", "cost_incurred", "net_cash"]
    assert rows[-1][0] == "TOTAL"
    assert Decimal(rows[-1][3]) == Decimal("27.00")


def test_transactions_qbo_export_is_a_three_column_journal(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    customer_id = make_customer(client, owner)
    vendor_id = make_vendor(service_db, company_id)
    now = datetime.now(timezone.utc)

    _pay_invoice(client, service_db, owner, customer_id, "80.00", paid_at=now)
    _received_po(service_db, company_id, vendor_id, owner_id, qty=2, unit_cost="10.00", received_at=now)

    resp = client.get(
        "/api/v1/reports/transactions/export.csv",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    rows = _parse_csv(resp.text)
    assert rows[0] == ["Date", "Description", "Amount"]
    # Exactly 3 columns per row, both a positive (revenue) and negative
    # (cost) entry present.
    data_rows = rows[1:]
    assert all(len(r) == 3 for r in data_rows)
    amounts = [Decimal(r[2]) for r in data_rows]
    assert any(a > 0 for a in amounts)
    assert any(a < 0 for a in amounts)
    assert sum(amounts) == Decimal("60.00")  # 80 revenue - 20 parts cost


def test_export_endpoints_are_gated_the_same_as_their_json_counterparts(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    for path in [
        "/api/v1/reports/ar-aging/export.csv",
        "/api/v1/reports/pnl/export.csv",
        "/api/v1/reports/cash-flow/export.csv",
        "/api/v1/reports/transactions/export.csv",
    ]:
        resp = client.get(path, headers=auth_headers(tech))
        assert resp.status_code == 403, f"{path} should be 403 for a technician"


def test_export_endpoints_scoped_to_tenant(client, service_db):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")
    customer_a = make_customer(client, owner_a)
    customer_b = make_customer(client, owner_b)
    now = datetime.now(timezone.utc)
    _pay_invoice(client, service_db, owner_a, customer_a, "11.00", paid_at=now)
    _pay_invoice(client, service_db, owner_b, customer_b, "999.00", paid_at=now)

    resp = client.get(
        "/api/v1/reports/pnl/export.csv",
        params={
            "start_date": (now - timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(owner_a),
    )
    rows = _parse_csv(resp.text)
    assert Decimal(rows[-1][1]) == Decimal("11.00")
