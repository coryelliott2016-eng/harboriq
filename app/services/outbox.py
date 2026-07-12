"""Outbox — queue non-DB side effects for dispatch AFTER commit.

Webhook-triggered receipts/emails/SMS are written here inside the same
transaction as the DB state change, then dispatched by a separate worker
after commit. This prevents 'receipt sent but invoice rolled back' bugs.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context


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


def dispatch_pending(db: Session, limit: int = 100) -> int:
    """Pull pending outbox events and mark dispatched.

    A real implementation would call the email/SMS/webhook transport here and
    move failures to dead_letter after max attempts. This is the skeleton.
    """
    rows = db.execute(
        text(
            """
            UPDATE outbox_events
               SET status = 'dispatched',
                   dispatched_at = now(),
                   attempts = attempts + 1
             WHERE id IN (
                 SELECT id FROM outbox_events
                  WHERE status = 'pending'
                  ORDER BY created_at
                  LIMIT :limit
                  FOR UPDATE SKIP LOCKED
             )
             RETURNING id
            """
        ),
        {"limit": limit},
    ).all()
    db.commit()
    return len(rows)
