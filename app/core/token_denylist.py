"""Redis-backed per-token (JTI) access-token denylist (Phase 17).

This module handles revocation of a single access token. User-wide access-token
revocation is tracked durably in `users.access_epoch` and checked by
`app.api.deps.get_current_principal`.

Design:
  - On logout (or any future forced-session-revocation path), the access
    token's `jti` is added to a Redis SET member with a TTL equal to the
    token's own remaining lifetime (`exp - now`). Once the token would
    have expired naturally anyway, the denylist entry is free to expire
    too -- there is no reason to remember a jti forever.
  - `get_current_principal` (`app.api.deps`) checks membership on every
    request, right after signature/expiry verification.
  - Fail-open on Redis errors, mirroring `app.core.rate_limit`'s
    documented rationale. This affects only per-token JTI revocation;
    persisted user-wide revocation remains effective during a Redis outage.
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
    """Test-only: clear denylist entries between test cases."""
    try:
        redis_client = get_redis()
        keys = redis_client.keys(f"{_KEY_PREFIX}:*")
        if keys:
            redis_client.delete(*keys)
    except RedisError:
        logger.warning("token_denylist.redis_unavailable_during_reset")


__all__ = [
    "denylist_token",
    "is_denylisted",
]
