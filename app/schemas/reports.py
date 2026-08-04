"""AR aging report schemas (Phase 8)."""
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
