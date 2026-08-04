"""Shared helper for scheduling a near-real-time outbox dispatch pass.

There is no Celery/Redis task queue in this stack yet (see README, "Email
delivery" — adding that infrastructure is out of scope for this phase).
FastAPI `BackgroundTasks` runs after the response has already been sent to
the client but still within the same process/request lifecycle, which keeps
delivery close to real-time without introducing a new moving part. The
natural next step once volume actually requires a real task queue is a
Celery worker consuming a Redis-backed queue instead of this.

Every route handler that enqueues an outbox event (rather than the service
layer — see `app/services/outbox.py`'s module docstring) should call
`dispatch_outbox_soon(background_tasks)` right after its own commit.
"""
from __future__ import annotations

from fastapi import BackgroundTasks

from app.services.outbox import dispatch_pending


def _dispatch_pending_outbox() -> None:
    """Run one outbox dispatch pass with its own short-lived DB session.

    Runs in a FastAPI `BackgroundTask`, which fires AFTER the response has
    already been returned — by then the request's own `get_db`/`get_service_db`
    session has already been closed (see `app.db.session.get_db`'s
    `finally: db.close()`), so this opens a fresh session rather than reusing
    a closed one. `dispatch_pending`'s own `SELECT ... FOR UPDATE SKIP LOCKED`
    claims rows globally across tenants, which is exactly what the service
    (BYPASSRLS) role is for — the same role `public_tokens`/webhook
    resolution already use for cross-tenant lookups.
    """
    from app.db.session import ServiceSession

    db = ServiceSession()
    try:
        dispatch_pending(db)
    finally:
        db.close()


def dispatch_outbox_soon(background_tasks: BackgroundTasks) -> None:
    """Schedule `_dispatch_pending_outbox` to run after the response is sent."""
    background_tasks.add_task(_dispatch_pending_outbox)
