"""Celery application (Phase 16).

Replaces two pieces of "no task queue yet" infrastructure that earlier
phases explicitly called out as temporary:

  * `app/services/outbox_dispatch.py`'s FastAPI `BackgroundTasks` dispatch
    (near-real-time, fires once per request that enqueued an event).
  * `app/jobs/dunning_sweep.py` / `app/jobs/geocode_backfill.py`'s "run me
    from an external cron" scripts (periodic, previously nothing actually
    scheduled them from *inside* this codebase).

Both now run as real Celery tasks (`app/tasks/*.py`) against a Redis broker
+ result backend, with Celery Beat driving the periodic sweeps. Critically,
every task below is a thin wrapper that calls the SAME underlying
claim-and-process functions the old code used
(`app.services.outbox.dispatch_pending`, `app.jobs.dunning_sweep.run`,
`app.jobs.geocode_backfill.run`) — the `FOR UPDATE SKIP LOCKED` claiming
semantics in `outbox.dispatch_pending` live in exactly one place, so a
Celery worker and (if ever invoked directly again) the old call sites can
never race each other with divergent logic.

Broker/backend: Redis, via `settings.redis_url` — the same Redis instance
the rate limiter uses (a different logical use, but one dependency to run
in development/production rather than two).
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "harboriq",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.outbox_tasks", "app.tasks.sweep_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Test suite only: `tests/conftest.py` flips this to True via an autouse
    # fixture so `.delay()` calls run the task body synchronously, in-process,
    # with no broker/worker required — the standard Celery testing pattern
    # (see docs.celeryq.dev, "Testing with Celery" -> `task_always_eager`).
    # False here is the real, production default: `.delay()` publishes to
    # Redis and a separate `celery -A app.core.celery_app worker` process
    # executes it.
    task_always_eager=False,
    task_eager_propagates=True,
    # Tasks in this app are all idempotent-by-construction claim-and-process
    # loops (SKIP LOCKED, WHERE ... IS NULL backfills) or safe to re-run, so
    # acknowledging late (after the task body completes) is the safer
    # default: a worker that crashes mid-task will have its message
    # redelivered rather than silently dropped.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Beat schedule: periodic sweeps that used to require an external cron
    # invoking `python -m app.jobs.dunning_sweep` / `geocode_backfill` now
    # run from inside this same stack. Cadence chosen to match what those
    # jobs' own docstrings and README already implied ("periodic", not
    # real-time) without hammering Nominatim's 1 req/sec geocoding limit or
    # re-running dunning more often than daily billing cycles need.
    beat_schedule={
        "dunning-sweep-hourly": {
            "task": "app.tasks.sweep_tasks.dunning_sweep_task",
            "schedule": crontab(minute=0),
        },
        "geocode-backfill-every-6-hours": {
            "task": "app.tasks.sweep_tasks.geocode_backfill_task",
            "schedule": crontab(minute=15, hour="*/6"),
        },
        "outbox-dispatch-every-minute": {
            "task": "app.tasks.outbox_tasks.dispatch_outbox_task",
            "schedule": 60.0,
        },
    },
)

__all__ = ["celery_app"]
