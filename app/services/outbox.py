"""Outbox — queue non-DB side effects for dispatch AFTER commit.

Webhook-triggered receipts/emails/SMS are written here inside the same
transaction as the DB state change, then dispatched by a separate worker
after commit. This prevents 'receipt sent but invoice rolled back' bugs.

`dispatch_pending` now actually sends email (via `app.services.email`)
instead of just marking rows dispatched. There is no Celery/Redis task queue
in this stack yet — adding that infrastructure is out of scope for this
phase (see README, "Email delivery"). Instead, `dispatch_pending` is invoked
via FastAPI `BackgroundTasks` scheduled right after each commit that
enqueues an event (in the route handler, not deep in the service layer),
which keeps delivery near-real-time without introducing new infrastructure.
The natural next step once volume actually requires a real task queue is a
Celery worker consuming a Redis-backed queue instead of this HTTP-request-
adjacent dispatch.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.tenant import tenant_context
from app.services import email

#: After this many failed attempts, a row moves to `dead_letter` instead of
#: staying `pending` forever (the `status` column already documents this
#: third state in its migration-0001 comment; this is the first thing to
#: actually use it).
MAX_DISPATCH_ATTEMPTS = 5


def enqueue(
    db: Session,
    company_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Append a non-DB side effect to the outbox. Returns the outbox row id."""
    import json

    with tenant_context(db, company_id):
        result = db.execute(
            text(
                """
                INSERT INTO outbox_events (company_id, event_type, payload)
                VALUES (:cid, :et, CAST(:payload AS jsonb))
                RETURNING id
                """
            ),
            {"cid": company_id, "et": event_type, "payload": json.dumps(payload)},
        )
        row = result.first()
    # NOTE: caller commits the transaction (outbox row persists only on commit,
    # which is the point — if the state change rolls back, no outbox event exists).
    return int(row.id)


def _build_email(event_type: str, payload: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (to, subject, text_body) for a known event type, or None.

    `None` means "not an email event" — dispatched immediately as a no-op
    success rather than retried forever (e.g. a future webhook/SMS event
    type that reuses this same outbox table).
    """
    base_url = settings.app_base_url.rstrip("/")

    if event_type == "auth.password_reset_requested":
        link = f"{base_url}/reset-password/{payload['reset_token']}"
        return (
            payload["email"],
            "Reset your HarborIQ password",
            "We received a request to reset your HarborIQ password.\n\n"
            f"Reset it here: {link}\n\n"
            "If you did not request this, you can safely ignore this email.",
        )

    if event_type == "user_invite.sent":
        link = f"{base_url}/accept-invite/{payload['invite_token']}"
        return (
            payload["email"],
            f"You're invited to join {payload['company_name']} on HarborIQ",
            f"{payload.get('inviter_name') or 'A teammate'} invited you to join "
            f"{payload['company_name']} on HarborIQ as {payload['role']}.\n\n"
            f"Accept your invite here: {link}\n\n"
            f"This link expires in {payload.get('ttl_hours', 168)} hours.",
        )

    if event_type == "invoice.send":
        # `pay_url` today is an API path (`/api/v1/public/invoice/{token}`),
        # not a frontend route — kept exactly as `send_invoice` already
        # returns it so this does not change the public-payment contract;
        # just relay it verbatim in the email body.
        link = payload["pay_url"]
        return (
            payload.get("customer_email") or "",
            "Your HarborIQ invoice is ready",
            f"Your invoice is ready to view and pay: {link}",
        )

    if event_type == "receipt.send":
        amount_cents = payload.get("amount_cents") or 0
        return (
            payload.get("customer_email") or "",
            "Payment receipt",
            f"Thanks for your payment of ${amount_cents / 100:.2f}. "
            f"Payment reference: {payload.get('payment_intent') or 'n/a'}.",
        )

    return None


def _dispatch_one(db: Session, row) -> bool:
    """Send one outbox row's email. Returns True on success."""
    built = _build_email(row.event_type, row.payload)
    if built is None:
        # Unknown/non-email event type: nothing to send, treat as a no-op
        # success so it does not spin forever waiting on a transport that
        # will never handle it.
        return True

    to, subject, text_body = built
    if not to:
        # No recipient resolvable from the payload — cannot be delivered by
        # retrying, so treat as a permanent failure (goes to dead_letter once
        # attempts are exhausted, same as any other send failure).
        return False

    return email.send_email(to, subject, text_body)


def dispatch_pending(db: Session, limit: int = 100) -> int:
    """Pull pending outbox events and attempt real delivery.

    Rows are claimed with `FOR UPDATE SKIP LOCKED` so concurrent dispatchers
    (multiple BackgroundTasks running close together) never double-send.
    A row that sends successfully is marked `dispatched`; a row that fails is
    left `pending` (so it is retried on the next dispatch pass) until
    `MAX_DISPATCH_ATTEMPTS` is reached, at which point it moves to
    `dead_letter` and stops being retried automatically.

    Returns the number of rows successfully dispatched.
    """
    claimed = db.execute(
        text(
            """
            SELECT id, company_id, event_type, payload, attempts
              FROM outbox_events
             WHERE status = 'pending'
             ORDER BY created_at
             LIMIT :limit
               FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    ).all()

    dispatched = 0
    for row in claimed:
        try:
            ok = _dispatch_one(db, row)
        except Exception as exc:  # noqa: BLE001 — a bad payload must not wedge the queue
            ok = False
            last_error = str(exc)
        else:
            last_error = None if ok else "send_email returned False"

        if ok:
            db.execute(
                text(
                    """
                    UPDATE outbox_events
                       SET status = 'dispatched',
                           dispatched_at = now(),
                           attempts = attempts + 1,
                           last_error = NULL
                     WHERE id = :id
                    """
                ),
                {"id": row.id},
            )
            dispatched += 1
        else:
            new_attempts = row.attempts + 1
            new_status = "dead_letter" if new_attempts >= MAX_DISPATCH_ATTEMPTS else "pending"
            db.execute(
                text(
                    """
                    UPDATE outbox_events
                       SET status = :status,
                           attempts = :attempts,
                           last_error = :error
                     WHERE id = :id
                    """
                ),
                {
                    "status": new_status,
                    "attempts": new_attempts,
                    "error": last_error,
                    "id": row.id,
                },
            )

    db.commit()
    return dispatched
