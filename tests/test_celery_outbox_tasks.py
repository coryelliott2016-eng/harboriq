"""Celery outbox/sweep tasks (Phase 16).

`app/tasks/outbox_tasks.py` and `app/tasks/sweep_tasks.py` are thin wrappers
around the pre-existing claim-and-process functions
(`app.services.outbox.dispatch_pending`, `app.jobs.dunning_sweep.run`,
`app.jobs.geocode_backfill.run`). These tests prove:

  1. The Celery task actually calls through to that same underlying
     function (no duplicated/divergent dispatch logic in the task layer).
  2. `dispatch_outbox_task` correctly claims and dispatches a real pending
     outbox row end-to-end (through `.delay()`, in eager mode per
     `tests/conftest.py`'s session-scoped fixture).
  3. `FOR UPDATE SKIP LOCKED` semantics are preserved: a row already locked
     by another transaction is skipped rather than raising or double-
     dispatching, exactly like `test_email_and_outbox_dispatch.py` already
     proves for `dispatch_pending` directly.
  4. `dispatch_outbox_soon` (the route-handler-facing helper) enqueues via
     Celery's `.delay()`, not FastAPI `BackgroundTasks`.
"""
from __future__ import annotations

import threading

from sqlalchemy import text

from app.core.celery_app import celery_app
from app.services import email, outbox
from app.tasks import outbox_tasks, sweep_tasks


def test_celery_conf_is_eager_in_tests():
    """The session-scoped autouse fixture in conftest.py must have flipped
    this on -- every other test in this file depends on it."""
    assert celery_app.conf.task_always_eager is True


def test_dispatch_outbox_task_calls_dispatch_pending(monkeypatch):
    calls = []
    monkeypatch.setattr(
        outbox_tasks.outbox, "dispatch_pending", lambda db: calls.append(db) or 3
    )
    result = outbox_tasks.dispatch_outbox_task.delay()
    assert result.get() == 3
    assert len(calls) == 1


def test_dispatch_outbox_task_end_to_end_sends_real_email(
    service_db, company_a, monkeypatch
):
    """A real pending outbox row, dispatched via the Celery task (not a
    direct `dispatch_pending` call), must actually be sent and marked
    dispatched -- proving the task is wired to the real function, not a
    stub."""
    sent = []
    monkeypatch.setattr(
        email,
        "send_email",
        lambda to, subject, body, html_body=None, attachments=None: (
            sent.append((to, subject)) or True
        ),
    )

    outbox_id = outbox.enqueue(
        service_db,
        company_a,
        "user_invite.sent",
        {
            "email": "tech@example.com",
            "invite_token": "tok123",
            "company_name": "Acme Marine",
            "role": "technician",
        },
    )
    service_db.commit()

    result = outbox_tasks.dispatch_outbox_task.delay()
    assert result.get() == 1
    assert len(sent) == 1
    assert sent[0][0] == "tech@example.com"

    row = service_db.execute(
        text("SELECT status FROM outbox_events WHERE id = :id"), {"id": outbox_id}
    ).first()
    assert row.status == "dispatched"


def test_dispatch_outbox_task_skips_a_locked_row(service_db, company_a, monkeypatch):
    """A row already locked (FOR UPDATE) by a concurrent transaction must be
    skipped by the task, not double-processed or raised on -- the exact
    SKIP LOCKED guarantee `app.services.outbox.dispatch_pending` documents,
    now proven through the Celery entrypoint."""
    from app.db.session import ServiceSession

    sent = []
    monkeypatch.setattr(
        email,
        "send_email",
        lambda to, subject, body, html_body=None, attachments=None: (
            sent.append(to) or True
        ),
    )

    outbox_id = outbox.enqueue(
        service_db,
        company_a,
        "user_invite.sent",
        {
            "email": "locked@example.com",
            "invite_token": "tokABC",
            "company_name": "Acme Marine",
            "role": "technician",
        },
    )
    service_db.commit()

    locker_db = ServiceSession()
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_lock():
        locker_db.execute(
            text("SELECT * FROM outbox_events WHERE id = :id FOR UPDATE"),
            {"id": outbox_id},
        )
        lock_acquired.set()
        release_lock.wait(timeout=5)
        locker_db.rollback()
        locker_db.close()

    t = threading.Thread(target=hold_lock)
    t.start()
    lock_acquired.wait(timeout=5)

    try:
        result = outbox_tasks.dispatch_outbox_task.delay()
        assert result.get() == 0
        assert sent == []
    finally:
        release_lock.set()
        t.join(timeout=5)


def test_dunning_sweep_task_calls_dunning_sweep_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sweep_tasks.dunning_sweep,
        "run",
        lambda: calls.append(1) or {"company_count": 0, "reminded_count": 0},
    )
    result = sweep_tasks.dunning_sweep_task.delay()
    assert result.get() == {"company_count": 0, "reminded_count": 0}
    assert calls == [1]


def test_geocode_backfill_task_calls_geocode_backfill_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sweep_tasks.geocode_backfill,
        "run",
        lambda force=False: calls.append(force)
        or {"company_count": 0, "customers_updated": 0, "users_updated": 0},
    )
    result = sweep_tasks.geocode_backfill_task.delay()
    assert result.get() == {
        "company_count": 0,
        "customers_updated": 0,
        "users_updated": 0,
    }
    assert calls == [False]

    result = sweep_tasks.geocode_backfill_task.delay(force=True)
    assert result.get()["company_count"] == 0
    assert calls == [False, True]


def test_dispatch_outbox_soon_enqueues_via_celery_delay(monkeypatch):
    """The route-facing helper must go through Celery's `.delay()`, not
    FastAPI BackgroundTasks -- this is the whole point of the Phase 16
    swap."""
    from app.services import outbox_dispatch

    calls = []
    monkeypatch.setattr(
        outbox_dispatch.dispatch_outbox_task, "delay", lambda: calls.append(1)
    )

    outbox_dispatch.dispatch_outbox_soon(background_tasks=None)
    assert calls == [1]
