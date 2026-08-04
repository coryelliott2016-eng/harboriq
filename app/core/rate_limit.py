"""In-process, per-IP fixed-window rate limiter.

Deliberately simple: a module-level dict keyed by (bucket, ip), counting
requests inside a fixed time window with no external dependency (no Redis,
no shared cache). This is enough to blunt a single-process credential-
stuffing or password-reset-spam attempt, but it does **not** coordinate
across multiple app instances — each process has its own counters, so a
horizontally-scaled deployment behind a load balancer effectively multiplies
the real limit by the number of processes/pods. The honest fix once traffic
justifies horizontally scaling is a Redis-backed limiter (e.g. a sliding
window or token bucket implemented with `INCR` + `EXPIRE`, or a Lua script
for atomicity) shared by every instance. That is out of scope for this phase
(see README, "Email delivery" / "Auth") — noted here rather than overstating
this as production-scale-ready.

Fixed-window (not sliding) is intentional: `Retry-After` is simply "seconds
until the window resets", which is easy to reason about and easy to test
without manipulating wall-clock time in a distributed way. A fixed window
can, in the worst case, allow up to 2x the nominal rate across a window
boundary — an acceptable trade-off for an anti-abuse speed bump, not a hard
security control (the account-lockout logic in `auth_service.login` is the
actual security control; this just raises the cost of hammering it).
"""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import settings


class _FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        # key -> (window_start_epoch, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> tuple[bool, int]:
        """Record one request for `key`. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            elapsed = now - window_start
            if elapsed >= self.window_seconds:
                # New window.
                window_start, count = now, 0
                elapsed = 0.0

            count += 1
            self._buckets[key] = (window_start, count)

            if count > self.limit:
                retry_after = max(1, int(self.window_seconds - elapsed))
                return False, retry_after
            return True, 0

    def reset(self) -> None:
        """Test helper — clear all counters between test cases."""
        with self._lock:
            self._buckets.clear()


#: One limiter instance per protected endpoint family, so exhausting the
#: login limiter does not also throttle password-reset requests from the
#: same IP.
_login_limiter = _FixedWindowLimiter(
    settings.rate_limit_requests_per_window, settings.rate_limit_window_seconds
)
_password_reset_limiter = _FixedWindowLimiter(
    settings.rate_limit_requests_per_window, settings.rate_limit_window_seconds
)


def _client_key(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def enforce_rate_limit(limiter: _FixedWindowLimiter, request: Request) -> None:
    """Raise 429 with a Retry-After header if `request`'s IP is over budget."""
    allowed, retry_after = limiter.hit(_client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, try again later",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_login_rate_limit(request: Request) -> None:
    enforce_rate_limit(_login_limiter, request)


def enforce_password_reset_rate_limit(request: Request) -> None:
    enforce_rate_limit(_password_reset_limiter, request)


def _reset_all_for_tests() -> None:
    """Test-only: clear both limiters so test order does not bleed state."""
    _login_limiter.reset()
    _password_reset_limiter.reset()
