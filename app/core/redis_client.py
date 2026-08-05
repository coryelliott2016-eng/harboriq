"""Shared Redis connection (Phase 16).

One process-wide connection pool, reused by the rate limiter
(`app/core/rate_limit.py`) and available to anything else that needs a
direct Redis handle. Celery gets its *own* connection via its broker/backend
URL (see `app/core/celery_app.py`) — Celery manages that connection's
lifecycle itself, so it deliberately does not share this pool.

`redis.Redis.from_url` is lazy: constructing the client does not connect
immediately, so importing this module never fails even if Redis is down.
The first real command (e.g. the rate limiter's Lua script `EVALSHA`/`EVAL`)
is where a connection failure would surface — see `rate_limit.py` for how
that is handled (fail-open, logged, never a 500 for the end user).
"""
from __future__ import annotations

from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Process-wide Redis client, lazily constructed on first use."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
