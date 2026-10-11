"""Optional Sentry error/performance reporting — graceful no-op when unset.

Mirrors the exact pattern already used by `app/services/stripe_billing.py`
(missing `stripe_api_key`) and `app/services/email.py` (missing `smtp_host`):
an unconfigured optional integration must never raise, log an error, or
change any observable behavior. Here that means `init_sentry()` is a no-op
whenever `settings.sentry_dsn` is empty (the default), which is also exactly
what every dev machine and the CI test suite run with.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import structlog

from app.core.config import settings

log = structlog.get_logger()


def exclude_public_demo_telemetry(event: dict, hint: dict) -> dict | None:
    """Do not send public demo credentials, request data or frame locals to Sentry."""
    request = event.get("request") or {}
    url = request.get("url", "")
    transaction = event.get("transaction", "")
    prefix = "/api/v1/public/intelligence/"
    if isinstance(url, str):
        try:
            if prefix in urlsplit(url).path:
                return None
        except ValueError:
            pass
    if isinstance(transaction, str) and (
        prefix in transaction or "app.api.v1.routes.intelligence." in transaction
    ):
        return None
    headers = request.get("headers") or {}
    items = headers.items() if isinstance(headers, dict) else headers
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            if str(item[0]).lower() == "x-demo-session":
                return None
    return event


def init_sentry() -> None:
    """Initialize the Sentry SDK if (and only if) `SENTRY_DSN` is configured.

    Safe to call unconditionally at import/startup time — with no DSN set
    this does nothing at all, not even import the `sentry_sdk` package's
    FastAPI integration eagerly, so a deployment that never wants Sentry
    pays zero cost for the dependency being installed.
    """
    if not settings.sentry_dsn:
        return

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            before_send=exclude_public_demo_telemetry,
            before_send_transaction=exclude_public_demo_telemetry,
            # Conservative default: capture a modest sample of transactions
            # for latency insight without shipping 100% of traffic to
            # Sentry, which gets expensive fast on a busy API. Tune per
            # deployment via Sentry project settings / a future env var if
            # this ever needs to be adjustable without a code change.
            traces_sample_rate=0.1,
        )
    except Exception:  # noqa: BLE001 — Sentry must never take the app down
        log.warning("sentry_init_failed", exc_info=True)
