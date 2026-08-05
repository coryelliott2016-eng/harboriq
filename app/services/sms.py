"""Outbound SMS transport — Twilio REST API when configured, console
fallback in dev.

Mirrors the exact graceful-degrade pattern `app/services/email.py` already
uses for SMTP: a missing/unset transport is a degraded dev experience, not a
reason to fail the request that queued the message. The outbox
(`app/services/outbox.py`) exists precisely so a transport failure here never
rolls back the business transaction that already committed.

Deliberately does NOT add the `twilio` PyPI SDK. `httpx` is already a
dependency and sending one SMS is a single `POST` to
`https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json` with HTTP
Basic auth (SID/auth token) — a full SDK would be a new dependency for a
provider that is not even configured in this workspace yet.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("harboriq.sms")

#: How much of the body to show in the console-fallback / error log line.
_LOG_BODY_TRUNCATE = 200

#: Twilio's REST API base — the account SID is interpolated into the path.
_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


def is_configured() -> bool:
    """True once real Twilio credentials are set (all three env vars)."""
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_from_number
    )


def send_sms(to: str, body: str) -> bool:
    """Send one SMS. Returns True on success (including console fallback).

    * Twilio not configured (the dev default) -> "console transport": log
      the message at INFO level and return True. Nothing is actually sent,
      which is fine for local development — the outbox row still gets
      marked dispatched, and a developer can read the message straight out
      of the logs, exactly like `app.services.email.send_email` when
      `smtp_host` is unset.
    * Twilio configured -> POST to the real Twilio REST API. Any HTTP or
      network failure is caught and logged, never raised — the caller
      (`outbox.dispatch_pending`) decides how to retry; SMS delivery must
      never raise into a request path that already committed its DB write.
    """
    if not is_configured():
        logger.info(
            "console-transport sms to=%s body=%r",
            to,
            body[:_LOG_BODY_TRUNCATE],
        )
        return True

    url = f"{_TWILIO_API_BASE}/Accounts/{settings.twilio_account_sid}/Messages.json"
    try:
        response = httpx.post(
            url,
            data={"To": to, "From": settings.twilio_from_number, "Body": body},
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Twilio send failed to=%s error=%s", to, exc)
        return False

    return True
