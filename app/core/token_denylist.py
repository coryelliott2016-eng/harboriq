"""Redis-backed access-token (JTI) denylist (Phase 17).

Closes the gap the README used to call out explicitly: "a revoked
session's access token stays valid until it expires ... stateful
access-token revocation remains out of scope." Access tokens are
short-lived stateless JWTs (see `app.core.security`), so there was
previously no way to invalidate one before its natural `exp` -- logging
out, or an admin forcibly ending a session, only ever revoked the
*refresh* token family (`app.services.auth.logout`/`_revoke_family`),
leaving any already-issued access token usable for up to
`access_token_ttl_minutes` more.

Design:
  - On logout (or any future forced-session-revocation path), the access
    token's `jti` is added to a Redis SET member with a TTL equal to the
    token's own remaining lifetime (`exp - now`). Once the token would
    have expired naturally anyway, the denylist entry is free to expire
    too -- there is no reason to remember a jti forever.
  - `get_current_principal` (`app.api.deps`) checks membership on every
    request, right after signature/expiry verification.
  - Fail-open on Redis errors, mirroring `app.core.rate_limit`'s
    documented rationale: a Redis outage should degrade this one extra
    layer of defense-in-depth, not take the entire API down. The
    underlying refresh-token revocation (which stops new access tokens
    from being minted) is unaffected by a Redis outage either way, and
    access tokens are short-lived by design -- the exposure window during
    a Redis outage is bounded by `access_token_ttl_minutes`, not
    unbounded.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from redis.exceptions import RedisError

from app.core.redis_client import get_redis

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "harboriq:jti_denylist"


def _key(jti: str) -> str:
    return f"{_KEY_PREFIX}:{jti}"


def denylist_token(jti: str, expires_at: datetime) -> None:
    """Mark `jti` as revoked until it would have expired naturally anyway.

    A no-op (logged) if `expires_at` is already in the past -- nothing to
    protect against once the token itself is dead on arrival.
    """
    ttl_seconds = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    if ttl_seconds <= 0:
        return
    try:
        redis_client = get_redis()
        redis_client.set(_key(jti), "1", ex=ttl_seconds)
    except RedisError:
        logger.warning("token_denylist.redis_unavailable_on_write", jti=jti)


def is_denylisted(jti: str) -> bool:
    try:
        redis_client = get_redis()
        return bool(redis_client.exists(_key(jti)))
    except RedisError:
        logger.warning("token_denylist.redis_unavailable_failing_open", jti=jti)
        return False


def _reset_all_for_tests() -> None:
    """Test-only: clear all denylist entries between test cases."""
    try:
        redis_client = get_redis()
        keys = redis_client.keys(f"{_KEY_PREFIX}:*")
        if keys:
            redis_client.delete(*keys)
    except RedisError:
        logger.warning("token_denylist.redis_unavailable_during_reset")


__all__ = ["denylist_token", "is_denylisted"]
