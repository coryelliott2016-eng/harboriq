"""Optional Sentry error/performance reporting — graceful no-op when unset.

Mirrors the exact pattern already used by `app/services/stripe_billing.py`
(missing `stripe_api_key`) and `app/services/email.py` (missing `smtp_host`):
an unconfigured optional integration must never raise, log an error, or
change any observable behavior. Here that means `init_sentry()` is a no-op
whenever `settings.sentry_dsn` is empty (the default), which is also exactly
what every dev machine and the CI test suite run with.
"""
from __future__ import annotations

import structlog

from app.core.config import settings

log = structlog.get_logger()


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
            # Conservative default: capture a modest sample of transactions
            # for latency insight without shipping 100% of traffic to
            # Sentry, which gets expensive fast on a busy API. Tune per
            # deployment via Sentry project settings / a future env var if
            # this ever needs to be adjustable without a code change.
            traces_sample_rate=0.1,
        )
    except Exception:  # noqa: BLE001 — Sentry must never take the app down
        log.warning("sentry_init_failed", exc_info=True)
