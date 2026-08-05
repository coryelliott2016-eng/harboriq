"""Shared helper for scheduling a near-real-time outbox dispatch pass.

Phase 16: this now enqueues a real Celery task
(`app.tasks.outbox_tasks.dispatch_outbox_task`) against the Redis broker,
replacing the previous FastAPI `BackgroundTasks` callback. The public
`dispatch_outbox_soon(background_tasks)` signature is unchanged on purpose
— every route handler that already calls it after its own commit keeps
working with no edits, whether or not it happens to also use
`background_tasks` for something else.

In the test suite, `celery_app.conf.task_always_eager` is flipped on by an
autouse fixture (see `tests/conftest.py`), so `.delay()` below runs the
task body synchronously and in-process — no broker, no worker, and no
behavior change from the pre-Phase-16 BackgroundTasks version as far as
tests using `TestClient` can tell (the dispatch pass has already happened
by the time `client.post(...)` returns, exactly as before).

Every route handler that enqueues an outbox event (rather than the service
layer — see `app/services/outbox.py`'s module docstring) should call
`dispatch_outbox_soon(background_tasks)` right after its own commit.
"""
from __future__ import annotations

from fastapi import BackgroundTasks

from app.tasks.outbox_tasks import dispatch_outbox_task


def dispatch_outbox_soon(background_tasks: BackgroundTasks) -> None:
    """Enqueue one outbox dispatch pass via Celery.

    `background_tasks` is accepted (and unused) purely to keep every call
    site's signature unchanged across the Phase 16 BackgroundTasks -> Celery
    swap; FastAPI route handlers still depend on it via `Depends`/parameter
    injection for other reasons in some files, and changing every call site
    to drop the parameter would be a larger, riskier diff than keeping it.
    """
    dispatch_outbox_task.delay()
