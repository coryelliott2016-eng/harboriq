"""Basic operational reports: AR aging (Phase 8), P&L / cash-flow / CSV
exports (Phase 14). Read-only, `require_operations`.

No reporting/analytics infrastructure exists yet (no warehouse, no
materialized views) -- this is a single, straightforward query bucketed in
Python. Fine at today's per-tenant data volumes; revisit if/when a real
analytics layer is built.

Phase 14 accounting methodology (read this before touching the numbers
below -- see also the README's "Accounting & reporting" section):

* **Revenue** = `payments.amount` for `status = 'succeeded'` rows whose
  `created_at` falls in the requested range, minus `refunds.amount` for
  refunds whose `created_at` falls in the same range. `payments` rows are
  written exactly once, inside `invoices.mark_paid_from_webhook`, at the
  moment Stripe confirms money actually moved -- so this is genuinely
  CASH-basis revenue (money collected), not accrual revenue (value
  invoiced). An invoice sent but not yet paid contributes $0 here; AR aging
  (Phase 8) is where unpaid/outstanding invoice value is reported instead.
  This is a deliberate, honest choice given what this schema actually
  tracks: there is no separate revenue-recognition ledger, and doing
  anything more "accrual-like" from `invoices.total`/`sent_at` would just
  be a different, no-more-defensible approximation.
* **Parts/materials cost** = `purchase_order_line_items.quantity_received *
  unit_cost`, summed for line items on purchase orders whose
  `received_at` falls in the range. This is COST INCURRED (accrual-ish --
  the moment stock was recorded as received), not cash paid to the vendor:
  this schema has no vendor-payment-date field, only `received_at`. Do not
  read this as "cash out to vendors" -- see the cash-flow section below,
  which surfaces this same caveat explicitly in its response.
* **Labor cost** = `SUM(EXTRACT(EPOCH FROM (clocked_out_at - clocked_in_at))
  / 3600.0 * users.hourly_rate)` for closed (`clocked_out_at IS NOT NULL`)
  `job_time_entries` whose `clocked_in_at` falls in the range, joined to the
  technician's `users.hourly_rate`. A technician with no `hourly_rate` set
  contributes an explicit "unavailable" marker, never a silent $0 --
  `labor_cost_unavailable` on the response tells the caller whether the
  labor-cost total is complete or is known to be undercounting real cost
  because at least one technician's hours could not be priced. Open
  (still-clocked-in) time entries are excluded -- their duration is not
  final yet.
* **Net** = revenue - parts cost - labor cost. If `labor_cost_unavailable`
  is true, `net` is still computed (parts + whatever labor cost COULD be
  priced) but the response flags it as a lower bound / potentially
  overstated net, never presented as a complete number silently.

Cash-flow methodology: cash IN is the same `payments` query as P&L revenue
(before subtracting refunds, which are their own line); cash OUT is the same
PO-received-line-items query as P&L parts cost, again labeled "cost
 incurred," not "cash paid," for the reason above.
"""
from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context

#: (bucket label, min days overdue inclusive, max days overdue inclusive-or-None)
_AGING_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("current", -(10**9), 0),
    ("1_30", 1, 30),
    ("31_60", 31, 60),
    ("61_90", 61, 90),
    ("90_plus", 91, None),
)


def _bucket_for(days_overdue: int) -> str:
    for label, low, high in _AGING_BUCKETS:
        if days_overdue < low:
            continue
        if high is None or days_overdue <= high:
            return label
    return "90_plus"  # unreachable given the ranges above; defensive fallback


def ar_aging_report(db: Session, company_id: uuid.UUID) -> dict[str, Any]:
    """Bucket every invoice with a positive `balance_due` by days overdue,
    grouped by customer.

    "Overdue" is measured against `due_date` when set; invoices with no
    `due_date` yet (e.g. sent without one) are bucketed as `current` since
    there is no date to be overdue against.
    """
    now = datetime.now(timezone.utc)

    with tenant_context(db, company_id):
        rows = db.execute(
            text(
                """
                SELECT i.id, i.customer_id, i.balance_due, i.due_date,
                       COALESCE(c.company_name,
                                NULLIF(BTRIM(COALESCE(c.first_name, '') || ' ' ||
                                             COALESCE(c.last_name, '')), ''),
                                'Unknown customer') AS customer_name
                  FROM invoices i
                  LEFT JOIN customers c ON c.id = i.customer_id
                 WHERE i.company_id = :cid AND i.balance_due > 0
                 ORDER BY customer_name, i.due_date NULLS FIRST
                """
            ),
            {"cid": company_id},
        ).all()

    by_customer: dict[str, dict[str, Any]] = {}
    totals: dict[str, Decimal] = {label: Decimal("0") for label, _, _ in _AGING_BUCKETS}
    grand_total = Decimal("0")

    for row in rows:
        days_overdue = (now - row.due_date).days if row.due_date is not None else 0
        bucket = _bucket_for(days_overdue)

        key = str(row.customer_id) if row.customer_id else "unknown"
        entry = by_customer.setdefault(
            key,
            {
                "customer_id": str(row.customer_id) if row.customer_id else None,
                "customer_name": row.customer_name,
                "buckets": {label: Decimal("0") for label, _, _ in _AGING_BUCKETS},
                "total": Decimal("0"),
                "invoice_count": 0,
            },
        )
        entry["buckets"][bucket] += row.balance_due
        entry["total"] += row.balance_due
        entry["invoice_count"] += 1

        totals[bucket] += row.balance_due
        grand_total += row.balance_due

    return {
        "as_of": now,
        "customers": sorted(by_customer.values(), key=lambda e: e["customer_name"] or ""),
        "bucket_totals": totals,
        "grand_total": grand_total,
    }


# ---------------------------------------------------------------------------
# Phase 14 — P&L, cash flow, CSV exports
# ---------------------------------------------------------------------------

def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _parse_range(
    start_date: datetime | None, end_date: datetime | None
) -> tuple[datetime, datetime]:
    """Normalize an optional (start_date, end_date) into a concrete UTC
    [start, end) range. Missing `start_date` defaults to the epoch (i.e.
    "everything up to end"); missing `end_date` defaults to now. Both are
    coerced to UTC-aware if a naive datetime slipped in from a query param.
    """
    now = datetime.now(timezone.utc)
    start = start_date or datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = end_date or now
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return start, end


def _revenue_rows(db: Session, company_id: uuid.UUID, start: datetime, end: datetime) -> list[Any]:
    """Succeeded payments (cash collected) in [start, end]."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT id, amount, created_at
                      FROM payments
                     WHERE company_id = :cid
                       AND status = 'succeeded'
                       AND created_at >= :start AND created_at <= :end
                     ORDER BY created_at
                    """
                ),
                {"cid": company_id, "start": start, "end": end},
            ).all()
        )


def _refund_rows(db: Session, company_id: uuid.UUID, start: datetime, end: datetime) -> list[Any]:
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT id, amount, created_at
                      FROM refunds
                     WHERE company_id = :cid
                       AND created_at >= :start AND created_at <= :end
                     ORDER BY created_at
                    """
                ),
                {"cid": company_id, "start": start, "end": end},
            ).all()
        )


def _parts_cost_rows(db: Session, company_id: uuid.UUID, start: datetime, end: datetime) -> list[Any]:
    """PO line items' received quantity * unit_cost, for POs whose
    `received_at` falls in range. Joining through `purchase_orders` for the
    `received_at` timestamp since line items carry no receipt date of their
    own."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT li.id, li.quantity_received, li.unit_cost,
                           po.received_at, po.id AS purchase_order_id
                      FROM purchase_order_line_items li
                      JOIN purchase_orders po ON po.id = li.purchase_order_id
                     WHERE li.company_id = :cid
                       AND po.received_at IS NOT NULL
                       AND po.received_at >= :start AND po.received_at <= :end
                       AND li.quantity_received > 0
                     ORDER BY po.received_at
                    """
                ),
                {"cid": company_id, "start": start, "end": end},
            ).all()
        )


def _labor_rows(db: Session, company_id: uuid.UUID, start: datetime, end: datetime) -> list[Any]:
    """Closed time entries with technician hourly_rate (NULL if unset --
    the caller must treat NULL as "unavailable," not 0)."""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT te.id, te.technician_id, te.clocked_in_at, te.clocked_out_at,
                           u.hourly_rate, u.full_name AS technician_name
                      FROM job_time_entries te
                      JOIN users u ON u.id = te.technician_id
                     WHERE te.company_id = :cid
                       AND te.clocked_out_at IS NOT NULL
                       AND te.clocked_in_at >= :start AND te.clocked_in_at <= :end
                     ORDER BY te.clocked_in_at
                    """
                ),
                {"cid": company_id, "start": start, "end": end},
            ).all()
        )


def pnl_report(
    db: Session,
    company_id: uuid.UUID,
    start_date: datetime | None,
    end_date: datetime | None,
) -> dict[str, Any]:
    """Simple cash-basis P&L for [start_date, end_date], grouped by month
    plus a totals row. See the module docstring for the exact methodology.
    """
    start, end = _parse_range(start_date, end_date)

    payments = _revenue_rows(db, company_id, start, end)
    refunds = _refund_rows(db, company_id, start, end)
    parts = _parts_cost_rows(db, company_id, start, end)
    labor = _labor_rows(db, company_id, start, end)

    months: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "revenue": Decimal("0"),
            "refunds": Decimal("0"),
            "parts_cost": Decimal("0"),
            "labor_cost": Decimal("0"),
            "labor_cost_unavailable": False,
            "unrated_technicians": set(),
        }
    )

    for row in payments:
        months[_month_key(row.created_at)]["revenue"] += row.amount
    for row in refunds:
        months[_month_key(row.created_at)]["refunds"] += row.amount
    for row in parts:
        months[_month_key(row.received_at)]["parts_cost"] += (
            Decimal(row.quantity_received) * row.unit_cost
        )
    for row in labor:
        key = _month_key(row.clocked_in_at)
        if row.hourly_rate is None:
            months[key]["labor_cost_unavailable"] = True
            months[key]["unrated_technicians"].add(
                row.technician_name or str(row.technician_id)
            )
            continue
        hours = Decimal(str((row.clocked_out_at - row.clocked_in_at).total_seconds() / 3600.0))
        months[key]["labor_cost"] += (hours * row.hourly_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    # Ensure every month with ANY activity is present even if e.g. revenue
    # was $0 that month but parts cost wasn't -- defaultdict already
    # guarantees this since every loop above touches `months[key]`.
    monthly = []
    totals = {
        "revenue": Decimal("0"),
        "refunds": Decimal("0"),
        "parts_cost": Decimal("0"),
        "labor_cost": Decimal("0"),
    }
    any_labor_unavailable = False
    all_unrated: set[str] = set()

    for month in sorted(months):
        m = months[month]
        net_revenue = m["revenue"] - m["refunds"]
        net = net_revenue - m["parts_cost"] - m["labor_cost"]
        monthly.append(
            {
                "month": month,
                "revenue": m["revenue"],
                "refunds": m["refunds"],
                "net_revenue": net_revenue,
                "parts_cost": m["parts_cost"],
                "labor_cost": m["labor_cost"],
                "labor_cost_unavailable": m["labor_cost_unavailable"],
                "unrated_technicians": sorted(m["unrated_technicians"]),
                "net": net,
            }
        )
        totals["revenue"] += m["revenue"]
        totals["refunds"] += m["refunds"]
        totals["parts_cost"] += m["parts_cost"]
        totals["labor_cost"] += m["labor_cost"]
        if m["labor_cost_unavailable"]:
            any_labor_unavailable = True
            all_unrated |= m["unrated_technicians"]

    total_net_revenue = totals["revenue"] - totals["refunds"]
    total_net = total_net_revenue - totals["parts_cost"] - totals["labor_cost"]

    return {
        "start_date": start,
        "end_date": end,
        "months": monthly,
        "totals": {
            "revenue": totals["revenue"],
            "refunds": totals["refunds"],
            "net_revenue": total_net_revenue,
            "parts_cost": totals["parts_cost"],
            "labor_cost": totals["labor_cost"],
            "labor_cost_unavailable": any_labor_unavailable,
            "unrated_technicians": sorted(all_unrated),
            "net": total_net,
        },
    }


def cash_flow_report(
    db: Session,
    company_id: uuid.UUID,
    start_date: datetime | None,
    end_date: datetime | None,
) -> dict[str, Any]:
    """Cash in (succeeded payments) vs. cost incurred (PO received line
    items -- NOT necessarily cash paid; see module docstring), grouped by
    month plus totals.
    """
    start, end = _parse_range(start_date, end_date)

    payments = _revenue_rows(db, company_id, start, end)
    refunds = _refund_rows(db, company_id, start, end)
    parts = _parts_cost_rows(db, company_id, start, end)

    months: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"cash_in": Decimal("0"), "refunds_out": Decimal("0"), "cost_incurred": Decimal("0")}
    )
    for row in payments:
        months[_month_key(row.created_at)]["cash_in"] += row.amount
    for row in refunds:
        months[_month_key(row.created_at)]["refunds_out"] += row.amount
    for row in parts:
        months[_month_key(row.received_at)]["cost_incurred"] += (
            Decimal(row.quantity_received) * row.unit_cost
        )

    monthly = []
    totals = {"cash_in": Decimal("0"), "refunds_out": Decimal("0"), "cost_incurred": Decimal("0")}
    for month in sorted(months):
        m = months[month]
        net_cash = m["cash_in"] - m["refunds_out"] - m["cost_incurred"]
        monthly.append(
            {
                "month": month,
                "cash_in": m["cash_in"],
                "refunds_out": m["refunds_out"],
                "cost_incurred": m["cost_incurred"],
                "net_cash": net_cash,
            }
        )
        totals["cash_in"] += m["cash_in"]
        totals["refunds_out"] += m["refunds_out"]
        totals["cost_incurred"] += m["cost_incurred"]

    total_net_cash = totals["cash_in"] - totals["refunds_out"] - totals["cost_incurred"]

    return {
        "start_date": start,
        "end_date": end,
        "months": monthly,
        "totals": {
            "cash_in": totals["cash_in"],
            "refunds_out": totals["refunds_out"],
            "cost_incurred": totals["cost_incurred"],
            "net_cash": total_net_cash,
        },
        "cost_incurred_caveat": (
            "cost_incurred reflects purchase-order line items marked received "
            "in this period (an accrual-style 'cost incurred' event), NOT a "
            "recorded vendor cash payment date -- this schema does not track "
            "when a vendor was actually paid. Treat cost_incurred as a "
            "reasonable proxy for cash out, not a literal cash-paid figure."
        ),
    }


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------

def _csv_response(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def pnl_report_csv(
    db: Session, company_id: uuid.UUID, start_date: datetime | None, end_date: datetime | None
) -> str:
    report = pnl_report(db, company_id, start_date, end_date)
    header = [
        "month", "revenue", "refunds", "net_revenue", "parts_cost",
        "labor_cost", "labor_cost_unavailable", "unrated_technicians", "net",
    ]
    rows = [
        [
            m["month"], m["revenue"], m["refunds"], m["net_revenue"], m["parts_cost"],
            m["labor_cost"], m["labor_cost_unavailable"],
            ";".join(m["unrated_technicians"]), m["net"],
        ]
        for m in report["months"]
    ]
    t = report["totals"]
    rows.append(
        [
            "TOTAL", t["revenue"], t["refunds"], t["net_revenue"], t["parts_cost"],
            t["labor_cost"], t["labor_cost_unavailable"],
            ";".join(t["unrated_technicians"]), t["net"],
        ]
    )
    return _csv_response(header, rows)


def cash_flow_report_csv(
    db: Session, company_id: uuid.UUID, start_date: datetime | None, end_date: datetime | None
) -> str:
    report = cash_flow_report(db, company_id, start_date, end_date)
    header = ["month", "cash_in", "refunds_out", "cost_incurred", "net_cash"]
    rows = [
        [m["month"], m["cash_in"], m["refunds_out"], m["cost_incurred"], m["net_cash"]]
        for m in report["months"]
    ]
    t = report["totals"]
    rows.append(["TOTAL", t["cash_in"], t["refunds_out"], t["cost_incurred"], t["net_cash"]])
    return _csv_response(header, rows)


def ar_aging_report_csv(db: Session, company_id: uuid.UUID) -> str:
    report = ar_aging_report(db, company_id)
    header = [
        "customer_name", "current", "days_1_30", "days_31_60", "days_61_90",
        "days_90_plus", "total", "invoice_count",
    ]
    rows = [
        [
            c["customer_name"], c["buckets"]["current"], c["buckets"]["1_30"],
            c["buckets"]["31_60"], c["buckets"]["61_90"], c["buckets"]["90_plus"],
            c["total"], c["invoice_count"],
        ]
        for c in report["customers"]
    ]
    b = report["bucket_totals"]
    rows.append(
        ["TOTAL", b["current"], b["1_30"], b["31_60"], b["61_90"], b["90_plus"],
         report["grand_total"], sum(c["invoice_count"] for c in report["customers"])]
    )
    return _csv_response(header, rows)


def transactions_export_csv(
    db: Session, company_id: uuid.UUID, start_date: datetime | None, end_date: datetime | None
) -> str:
    """QuickBooks Online-importable 3-column journal CSV: Date, Description,
    Amount. Covers invoiced-revenue cash collected (positive amounts) and
    received PO costs (negative amounts) for the period -- see the README's
    "CSV / QuickBooks-compatible exports" section for the column-format
    caveat (verify against QBO's own current import tool before relying on
    this blindly).
    """
    start, end = _parse_range(start_date, end_date)
    payments = _revenue_rows(db, company_id, start, end)
    refunds = _refund_rows(db, company_id, start, end)
    parts = _parts_cost_rows(db, company_id, start, end)

    entries: list[tuple[datetime, str, Decimal]] = []
    for row in payments:
        entries.append((row.created_at, f"Invoice payment received ({row.id})", row.amount))
    for row in refunds:
        entries.append((row.created_at, f"Refund issued ({row.id})", -row.amount))
    for row in parts:
        amount = -(Decimal(row.quantity_received) * row.unit_cost)
        entries.append(
            (row.received_at, f"Purchase order parts received (PO {row.purchase_order_id})", amount)
        )

    entries.sort(key=lambda e: e[0])
    header = ["Date", "Description", "Amount"]
    rows = [[dt.strftime("%m/%d/%Y"), desc, amount] for dt, desc, amount in entries]
    return _csv_response(header, rows)
