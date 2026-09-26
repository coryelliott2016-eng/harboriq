# ADR 0002 — Transactional outbox for side effects

Status: Accepted

## Context
Sending an invoice or estimate must both change state and email the
customer. Calling SMTP inside the request risks "state changed, email lost"
or "email sent, transaction rolled back."

## Decision
Business code inserts an `outbox_events` row in the same transaction
(`app/services/outbox.py`). Celery beat runs the dispatcher every 60 seconds
(`app/core/celery_app.py`); failures retry and move to `dead_letter` after 5
attempts (`app/services/outbox_dispatch.py`).

## Consequences
- State change and queued email are atomic.
- Email is eventually delivered, not instant; dead letters need an operator
  (SQL today; no admin UI).
- With no SMTP configured, the dispatcher logs messages instead of sending
  — useful for local dev, but production **must** configure SMTP.
