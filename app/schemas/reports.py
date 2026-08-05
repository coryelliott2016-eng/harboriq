"""AR aging report schemas (Phase 8) + P&L / cash-flow schemas (Phase 14)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AgingBuckets(BaseModel):
    current: Decimal
    #: Field names cannot start with a digit in Python/Pydantic, hence the
    #: `_days` suffix rather than mirroring `1-30` etc. verbatim.
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_90_plus: Decimal


class CustomerAging(BaseModel):
    customer_id: str | None
    customer_name: str
    buckets: AgingBuckets
    total: Decimal
    invoice_count: int


class ArAgingReport(BaseModel):
    as_of: datetime
    customers: list[CustomerAging]
    bucket_totals: AgingBuckets
    grand_total: Decimal


# --- P&L report (Phase 14) ---
# Mirrors app/services/reports.py::pnl_report exactly. See that module's
# docstring for the exact revenue/cost/labor methodology and the
# accrual-vs-cash caveats.


class PnlMonth(BaseModel):
    month: str  # "YYYY-MM"
    revenue: Decimal
    refunds: Decimal
    net_revenue: Decimal
    parts_cost: Decimal
    labor_cost: Decimal
    #: True if at least one technician with time entries in this month has
    #: no `hourly_rate` set -- `labor_cost` is then a KNOWN UNDERCOUNT, not
    #: a complete figure. Never silently treated as $0.
    labor_cost_unavailable: bool
    unrated_technicians: list[str]
    net: Decimal


class PnlTotals(BaseModel):
    revenue: Decimal
    refunds: Decimal
    net_revenue: Decimal
    parts_cost: Decimal
    labor_cost: Decimal
    labor_cost_unavailable: bool
    unrated_technicians: list[str]
    net: Decimal


class PnlReport(BaseModel):
    start_date: datetime
    end_date: datetime
    months: list[PnlMonth]
    totals: PnlTotals


# --- Cash flow report (Phase 14) ---


class CashFlowMonth(BaseModel):
    month: str
    cash_in: Decimal
    refunds_out: Decimal
    #: PO line items received in-period -- "cost incurred," NOT a recorded
    #: vendor cash-payment date (this schema has none). See
    #: `cost_incurred_caveat` on the report itself.
    cost_incurred: Decimal
    net_cash: Decimal


class CashFlowTotals(BaseModel):
    cash_in: Decimal
    refunds_out: Decimal
    cost_incurred: Decimal
    net_cash: Decimal


class CashFlowReport(BaseModel):
    start_date: datetime
    end_date: datetime
    months: list[CashFlowMonth]
    totals: CashFlowTotals
    cost_incurred_caveat: str
