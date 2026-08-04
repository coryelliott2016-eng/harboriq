"""Automated dunning sweep — `python -m app.jobs.dunning_sweep`.

There is no Celery/Redis task queue in this stack yet (Phase 16, per the
roadmap) — this is a plain script meant to be invoked by an external
scheduler (cron, a CI scheduled workflow, a container's entrypoint timer,
etc.), the same "no new infrastructure yet" posture `outbox_dispatch.py`
already documents for near-real-time email delivery.

Iterates every company (using the SERVICE session, BYPASSRLS) and calls
`app.services.billing.run_dunning_sweep` for each, then runs one outbox
dispatch pass so the queued `invoice.dunning_reminder` emails actually go
out in the same run rather than waiting for the next HTTP request to
trigger `dispatch_outbox_soon`.

The same logic is also reachable per-tenant, on demand, via
`POST /billing/dunning/run` (`app/api/v1/routes/billing.py`) for an admin
who wants to trigger it manually without waiting for the scheduled run.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import ServiceSession
from app.services import billing, outbox

logger = logging.getLogger("harboriq.jobs.dunning_sweep")


def run() -> dict[str, int]:
    """Run the sweep for every company. Returns `{company_count, reminded_count}`."""
    db = ServiceSession()
    try:
        company_ids = [row.id for row in db.execute(text("SELECT id FROM companies"))]

        reminded_count = 0
        for company_id in company_ids:
            result = billing.run_dunning_sweep(db, company_id)
            reminded_count += result["count"]
            if result["count"]:
                logger.info(
                    "dunning sweep: company=%s reminded=%d", company_id, result["count"]
                )

        dispatched = outbox.dispatch_pending(db)
        logger.info(
            "dunning sweep complete: companies=%d reminded=%d dispatched=%d",
            len(company_ids),
            reminded_count,
            dispatched,
        )
        return {"company_count": len(company_ids), "reminded_count": reminded_count}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
