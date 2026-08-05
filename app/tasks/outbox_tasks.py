"""Celery task wrapping outbox dispatch (Phase 16).

Replaces `app/services/outbox_dispatch.py`'s FastAPI `BackgroundTasks` call
with a real Celery task. `dispatch_outbox_task` calls the exact same
`app.services.outbox.dispatch_pending` function the old BackgroundTasks path
called — this file adds no claiming/dispatch logic of its own, so the
`SELECT ... FOR UPDATE SKIP LOCKED` semantics that make concurrent
dispatch-pass safety possible continue to live in exactly one place.

Two ways this task runs:

  * On Celery Beat's schedule (`outbox-dispatch-every-minute` in
    `app/core/celery_app.py`) — the periodic safety net that guarantees an
    event is never stuck in `pending` for more than ~1 minute even if
    nothing else ever triggers a pass.
  * Enqueued immediately after a request that creates an outbox event (see
    `app/services/outbox_dispatch.py::dispatch_outbox_soon`, updated in
    this same phase to call `.delay()` instead of scheduling a
    `BackgroundTasks` callback) — for near-real-time delivery, same intent
    as before, now via the broker instead of an in-process callback.
"""
from __future__ import annotations

import structlog

from app.core.celery_app import celery_app
from app.db.session import ServiceSession
from app.services import outbox

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.tasks.outbox_tasks.dispatch_outbox_task")
def dispatch_outbox_task() -> int:
    """Run one outbox dispatch pass. Returns the number of events dispatched.

    Opens its own short-lived SERVICE (BYPASSRLS) session, exactly like the
    old `_dispatch_pending_outbox` BackgroundTask did — `dispatch_pending`
    claims rows across every tenant in one pass, which requires bypassing
    RLS the same way webhook/public-token resolution already does.
    """
    db = ServiceSession()
    try:
        dispatched = outbox.dispatch_pending(db)
        if dispatched:
            logger.info("outbox_task.dispatched", count=dispatched)
        return dispatched
    finally:
        db.close()
