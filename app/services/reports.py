"""Basic operational reports (Phase 8: AR aging). Read-only, `require_operations`.

No reporting/analytics infrastructure exists yet (no warehouse, no
materialized views) -- this is a single, straightforward query bucketed in
Python. Fine at today's per-tenant data volumes; revisit if/when a real
analytics layer is built.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
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
