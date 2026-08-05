"""Reporting endpoints. `require_operations` (owner/admin/office) — same
gate as invoices/customers, since AR aging is a front-of-house billing
concern, not an owner/admin-only one. Phase 14 adds P&L, cash flow, and CSV
exports (including a QuickBooks Online-importable transactions journal)
under the same gate.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.schemas.reports import (
    AgingBuckets,
    ArAgingReport,
    CashFlowMonth,
    CashFlowReport,
    CashFlowTotals,
    CustomerAging,
    PnlMonth,
    PnlReport,
    PnlTotals,
)
from app.services import reports as service

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(require_operations)]
)


def _csv(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _to_buckets(raw: dict) -> AgingBuckets:
    return AgingBuckets(
        current=raw["current"],
        days_1_30=raw["1_30"],
        days_31_60=raw["31_60"],
        days_61_90=raw["61_90"],
        days_90_plus=raw["90_plus"],
    )


@router.get("/ar-aging", response_model=ArAgingReport)
def ar_aging(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Outstanding balances bucketed by days overdue, grouped by customer."""
    result = service.ar_aging_report(db, company_id)
    return ArAgingReport(
        as_of=result["as_of"],
        customers=[
            CustomerAging(
                customer_id=c["customer_id"],
                customer_name=c["customer_name"],
                buckets=_to_buckets(c["buckets"]),
                total=c["total"],
                invoice_count=c["invoice_count"],
            )
            for c in result["customers"]
        ],
        bucket_totals=_to_buckets(result["bucket_totals"]),
        grand_total=result["grand_total"],
    )


@router.get("/ar-aging/export.csv")
def ar_aging_export_csv(
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """AR aging (Phase 8 report), CSV export (Phase 14)."""
    content = service.ar_aging_report_csv(db, company_id)
    return _csv(content, "ar_aging.csv")


@router.get("/pnl", response_model=PnlReport)
def pnl(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Simple cash-basis P&L for the given date range, grouped by month plus
    a totals row. See `app/services/reports.py`'s module docstring for the
    exact revenue/cost/labor methodology and accrual-vs-cash caveats.
    """
    result = service.pnl_report(db, company_id, start_date, end_date)
    return PnlReport(
        start_date=result["start_date"],
        end_date=result["end_date"],
        months=[PnlMonth(**m) for m in result["months"]],
        totals=PnlTotals(**result["totals"]),
    )


@router.get("/pnl/export.csv")
def pnl_export_csv(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    content = service.pnl_report_csv(db, company_id, start_date, end_date)
    return _csv(content, "pnl.csv")


@router.get("/cash-flow", response_model=CashFlowReport)
def cash_flow(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """Cash in (payments received) vs. cost incurred (PO received line
    items) for the given date range. See `app/services/reports.py`'s module
    docstring for why "cost incurred" is explicitly NOT the same as "cash
    paid" in this schema.
    """
    result = service.cash_flow_report(db, company_id, start_date, end_date)
    return CashFlowReport(
        start_date=result["start_date"],
        end_date=result["end_date"],
        months=[CashFlowMonth(**m) for m in result["months"]],
        totals=CashFlowTotals(**result["totals"]),
        cost_incurred_caveat=result["cost_incurred_caveat"],
    )


@router.get("/cash-flow/export.csv")
def cash_flow_export_csv(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    content = service.cash_flow_report_csv(db, company_id, start_date, end_date)
    return _csv(content, "cash_flow.csv")


@router.get("/transactions/export.csv")
def transactions_export_csv(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    company_id: uuid.UUID = Depends(get_current_company_id),
):
    """QuickBooks Online-importable 3-column journal CSV (date, description,
    amount) covering invoiced revenue collected and received PO costs for
    the period -- see the README's "CSV / QuickBooks-compatible exports"
    section. This is an export bridge, NOT a live OAuth sync (see the
    README's "Future: live QuickBooks/Xero sync" section for what that would
    require).
    """
    content = service.transactions_export_csv(db, company_id, start_date, end_date)
    return _csv(content, "transactions_qbo.csv")
