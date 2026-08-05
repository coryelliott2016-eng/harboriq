"""Automated recurring monthly slip storage billing sweep (Phase 17).

Mirrors `app.jobs.dunning_sweep`'s shape exactly: iterate every company
(SERVICE session, BYPASSRLS) and call the per-company billing function for
each, so the same "one script, run by Celery Beat or invocable standalone"
pattern applies here as it does to dunning. See
`app.services.slip_reservations.generate_recurring_monthly_charges_for_company`
for the actual idempotent billing logic — this module only fans it out
across tenants and reports totals.

Idempotency lives entirely in the service layer (one `storage`-kind line
item per reservation per calendar month); running this sweep twice in the
same month, or invoking it both from Celery Beat and manually in the same
period, never double-charges a reservation. See
`tests/test_slip_recurring_billing.py`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.db.session import ServiceSession
from app.services import slip_reservations

logger = logging.getLogger("harboriq.jobs.slip_storage_billing_sweep")


def run(*, as_of: date | None = None) -> dict[str, int]:
    """Bill every active slip reservation for the calendar month containing
    `as_of` (defaults to today, UTC), across every company.

    Returns `{"company_count", "reservations_considered", "charges_created"}`.
    """
    resolved_as_of = as_of or datetime.now(timezone.utc).date()

    db = ServiceSession()
    try:
        company_ids = [row.id for row in db.execute(text("SELECT id FROM companies"))]

        reservations_considered = 0
        charges_created = 0
        for company_id in company_ids:
            result = slip_reservations.generate_recurring_monthly_charges_for_company(
                db, company_id, as_of=resolved_as_of
            )
            reservations_considered += result["reservations_considered"]
            charges_created += result["charges_created"]
            if result["charges_created"]:
                logger.info(
                    "slip storage billing sweep: company=%s charges_created=%d",
                    company_id,
                    result["charges_created"],
                )

        logger.info(
            "slip storage billing sweep complete: companies=%d considered=%d created=%d",
            len(company_ids),
            reservations_considered,
            charges_created,
        )
        return {
            "company_count": len(company_ids),
            "reservations_considered": reservations_considered,
            "charges_created": charges_created,
        }
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
