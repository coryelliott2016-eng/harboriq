"""Redis-backed, per-IP fixed-window rate limiter (Phase 16).

Replaces the original in-process dict/threading.Lock implementation (see
git history prior to Phase 16) with the exact upgrade that file's own
docstring called for: counters now live in Redis, keyed by
`{bucket}:{ip}`, so every app process/pod enforces the *same* limit against
the *same* counter — a client cannot reset its budget just by landing on a
different instance behind a load balancer.

Thresholds, behavior, and the public interface
(`enforce_login_rate_limit`/`enforce_password_reset_rate_limit`/
`_reset_all_for_tests`) are unchanged from the pre-Phase-16 version — this is
an implementation swap only, not a policy change. Fixed-window (not sliding)
remains intentional for the same reason as before: `Retry-After` is simply
"seconds until the window resets", which is easy to reason about, and a
fixed window's worst-case ~2x burst at a window boundary is an acceptable
trade-off for an anti-abuse speed bump (the account-lockout logic in
`auth_service.login` is the actual security control; this just raises the
cost of hammering it).

Atomicity: incrementing the counter and setting/reading its expiry must
happen as one atomic unit, or two concurrent requests could each see a
"first hit of a new window" and both slip through. A Lua script run via
`EVAL` is how Redis guarantees that — the whole script runs as a single,
uninterruptible step server-side, which plain `INCR` + `EXPIRE` (two round
trips) cannot guarantee under concurrency.

Fail-open on Redis errors: if Redis is unreachable, requests are allowed
through rather than raising a 500 for every login attempt. A rate limiter
that is down should not become an outage for the feature it protects —
this mirrors the "graceful degradation" principle used everywhere else in
this codebase (SMTP, Twilio, Sentry, geocoding). The failure is logged so
it is visible in observability, not silent.
"""
from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import get_redis

logger = structlog.get_logger(__name__)

#: Redis key prefix so rate-limit keys are visibly namespaced and trivial to
#: flush independently of any other key this app or others might store in
#: the same Redis instance/database.
_KEY_PREFIX = "harboriq:ratelimit"

#: Atomic fixed-window counter: increments `key`, sets its TTL only on the
#: very first hit of a new window (so the window doesn't keep sliding), and
#: returns both the new count and the key's current remaining TTL so the
#: caller can compute Retry-After without a second round trip.
_LUA_FIXED_WINDOW = """
local key = KEYS[1]
local window_seconds = tonumber(ARGV[1])
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window_seconds)
end
local ttl = redis.call('TTL', key)
if ttl < 0 then
    -- Defensive: a key with no TTL (e.g. INCR raced a concurrent EXPIRE in
    -- a way that lost it) would otherwise never reset. Re-arm it.
    redis.call('EXPIRE', key, window_seconds)
    ttl = window_seconds
end
return {count, ttl}
"""


class _RedisFixedWindowLimiter:
    def __init__(self, bucket: str, limit: int, window_seconds: int) -> None:
        self.bucket = bucket
        self.limit = limit
        self.window_seconds = window_seconds

    def _key(self, identity: str) -> str:
        return f"{_KEY_PREFIX}:{self.bucket}:{identity}"

    def hit(self, identity: str) -> tuple[bool, int]:
        """Record one request for `identity`. Returns (allowed, retry_after_seconds)."""
        try:
            redis_client = get_redis()
            count, ttl = redis_client.eval(
                _LUA_FIXED_WINDOW, 1, self._key(identity), self.window_seconds
            )
        except RedisError:
            logger.warning(
                "rate_limit.redis_unavailable_failing_open",
                bucket=self.bucket,
            )
            return True, 0

        count, ttl = int(count), int(ttl)
        if count > self.limit:
            return False, max(1, ttl)
        return True, 0

    def reset(self) -> None:
        """Test helper — clear all counters for this bucket between test cases."""
        try:
            redis_client = get_redis()
            keys = redis_client.keys(f"{_KEY_PREFIX}:{self.bucket}:*")
            if keys:
                redis_client.delete(*keys)
        except RedisError:
            logger.warning("rate_limit.redis_unavailable_during_reset", bucket=self.bucket)


#: One limiter instance per protected endpoint family, so exhausting the
#: login limiter does not also throttle password-reset requests from the
#: same IP. Separate Redis key buckets give the same isolation the old
#: separate in-process dicts gave.
_login_limiter = _RedisFixedWindowLimiter(
    "login", settings.rate_limit_requests_per_window, settings.rate_limit_window_seconds
)
_password_reset_limiter = _RedisFixedWindowLimiter(
    "password_reset",
    settings.rate_limit_requests_per_window,
    settings.rate_limit_window_seconds,
)
# Authenticated endpoint: identity is user_id, not IP. A stolen session
# spoofing technician location (marine threat model Scenario 2) is the
# threat; per-IP limiting would miss a mobile tech whose IP rotates and
# would not stop a single compromised bearer token.
_location_ping_limiter = _RedisFixedWindowLimiter(
    "location_ping",
    settings.location_ping_rate_limit_per_window,
    settings.location_ping_rate_limit_window_seconds,
)


def _client_key(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def enforce_rate_limit(limiter: _RedisFixedWindowLimiter, request: Request) -> None:
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


def enforce_rate_limit_for_identity(
    limiter: _RedisFixedWindowLimiter, identity: str, *, detail: str = "too many requests, try again later"
) -> None:
    """Raise 429 if `identity` (any opaque key — user id, IP, etc.) is over budget."""
    allowed, retry_after = limiter.hit(identity)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


def enforce_location_ping_rate_limit(user_id: str) -> None:
    """Per-user throttle for POST /users/me/location-ping (threat model Scenario 2)."""
    enforce_rate_limit_for_identity(
        _location_ping_limiter,
        user_id,
        detail="location ping rate limit exceeded",
    )


def _reset_all_for_tests() -> None:
    """Test-only: clear all limiters so test order does not bleed state."""
    _login_limiter.reset()
    _password_reset_limiter.reset()
    _location_ping_limiter.reset()
