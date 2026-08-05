"""Celery tasks wrapping the periodic sweep jobs (Phase 16).

Both tasks below are thin wrappers that call the exact same functions the
old "invoke me from an external cron" scripts called
(`app.jobs.dunning_sweep.run` / `app.jobs.geocode_backfill.run`) — no sweep
logic is duplicated here. Celery Beat now drives their schedule (see
`app/core/celery_app.py`'s `beat_schedule`) instead of requiring an operator
to wire up an external cron job, but the underlying `run()` functions remain
independently invocable exactly as before (`python -m app.jobs.dunning_sweep`,
`python -m app.jobs.geocode_backfill`, and the on-demand
`POST /admin/geocode-backfill` route) for manual/CI use.
"""
from __future__ import annotations

import structlog

from app.core.celery_app import celery_app
from app.jobs import dunning_sweep, geocode_backfill, slip_storage_billing_sweep

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.tasks.sweep_tasks.dunning_sweep_task")
def dunning_sweep_task() -> dict[str, int]:
    """Run the dunning sweep for every company. See `app.jobs.dunning_sweep.run`."""
    result = dunning_sweep.run()
    logger.info("sweep_task.dunning_complete", **result)
    return result


@celery_app.task(name="app.tasks.sweep_tasks.geocode_backfill_task")
def geocode_backfill_task(force: bool = False) -> dict[str, int]:
    """Run the geocode backfill for every company. See `app.jobs.geocode_backfill.run`."""
    result = geocode_backfill.run(force=force)
    logger.info("sweep_task.geocode_backfill_complete", **result)
    return result


@celery_app.task(name="app.tasks.sweep_tasks.slip_storage_billing_sweep_task")
def slip_storage_billing_sweep_task() -> dict[str, int]:
    """Bill every active slip reservation for the current calendar month,
    across every company. See `app.jobs.slip_storage_billing_sweep.run` --
    idempotent by (reservation, calendar month), so a redundant/late-retried
    run within the same month never double-charges.
    """
    result = slip_storage_billing_sweep.run()
    logger.info("sweep_task.slip_storage_billing_complete", **result)
    return result
