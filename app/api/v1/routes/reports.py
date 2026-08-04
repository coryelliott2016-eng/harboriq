"""Reporting endpoints. `require_operations` (owner/admin/office) — same
gate as invoices/customers, since AR aging is a front-of-house billing
concern, not an owner/admin-only one.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_company_id, get_db, require_operations
from app.schemas.reports import AgingBuckets, ArAgingReport, CustomerAging
from app.services import reports as service

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(require_operations)]
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
