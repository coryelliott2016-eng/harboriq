"""Celery wrappers for periodic Marine Signals work."""
from __future__ import annotations

import structlog

from app.core.celery_app import celery_app
from app.jobs import marine_signals_sweep

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.tasks.marine_signals_tasks.refresh_marine_signals_task")
def refresh_marine_signals_task() -> dict[str, int]:
    result = marine_signals_sweep.refresh_all_sources()
    logger.info("marine_signals.refresh_complete", **result)
    return result


@celery_app.task(name="app.tasks.marine_signals_tasks.weekly_marine_signals_digest_task")
def weekly_marine_signals_digest_task() -> dict[str, int]:
    result = marine_signals_sweep.send_weekly_digests()
    logger.info("marine_signals.digest_complete", **result)
    return result
