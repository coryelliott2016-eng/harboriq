"""Fail-closed, Redis-only limits. No raw IPs or bearer tokens are stored."""
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import redis
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas.intelligence import DemoSessionResponse

SESSION_TTL = 900
SESSION_QUOTA = 5
DAY_TTL = 172800
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")

# Both admission counters and session creation happen in one atomic operation.
CREATE_SESSION = """
local ip = tonumber(redis.call('GET', KEYS[1]) or '0')
local day = tonumber(redis.call('GET', KEYS[2]) or '0')
if ip >= 3 or day >= tonumber(ARGV[1]) then return 0 end
if redis.call('EXISTS', KEYS[3]) == 1 then return -1 end
redis.call('INCR', KEYS[1])
if ip == 0 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
redis.call('INCR', KEYS[2])
if day == 0 then redis.call('EXPIRE', KEYS[2], ARGV[3]) end
redis.call('SET', KEYS[3], ARGV[4], 'EX', ARGV[2])
return 1
"""

# Reserve before calling NOAA: failed upstream attempts also spend the budget.
RESERVE_CALL = """
local remaining = redis.call('GET', KEYS[1])
if not remaining then return -1 end
if tonumber(remaining) <= 0 then return -2 end
local day = tonumber(redis.call('GET', KEYS[2]) or '0')
if day >= tonumber(ARGV[1]) then return -3 end
local result = redis.call('DECR', KEYS[1])
redis.call('INCR', KEYS[2])
if day == 0 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
return result
"""


@lru_cache(maxsize=1)
def get_demo_redis():
    return redis.Redis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=2, socket_timeout=2,
    )


def _digest(value: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _session_key(token: str) -> str:
    return f"intelligence:session:{_digest('session:' + token)}"


def _day_key(kind: str) -> str:
    return f"intelligence:{kind}:{datetime.now(UTC).date().isoformat()}"


def _eval(script: str, keys: list[str], *args) -> int:
    try:
        return int(get_demo_redis().eval(script, len(keys), *keys, *args))
    except (RedisError, OSError, ValueError, TypeError) as exc:
        raise HTTPException(503, "The public demo is temporarily unavailable.") from exc


def create_session(ip: str) -> DemoSessionResponse:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=SESSION_TTL)
    result = _eval(
        CREATE_SESSION,
        [f"intelligence:ip:{_digest('ip:' + ip)}", _day_key("sessions"), _session_key(token)],
        settings.intelligence_demo_daily_session_budget, SESSION_TTL, DAY_TTL, SESSION_QUOTA,
    )
    if result == 0:
        raise HTTPException(429, "Demo session limit reached. Please try again later.")
    if result != 1:
        raise HTTPException(503, "The public demo is temporarily unavailable.")
    return DemoSessionResponse(
        session_token=token, expires_at=expires, requests_remaining=SESSION_QUOTA,
    )


def reserve_call(token: str) -> int:
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(401, "A valid, unexpired demo session is required.")
    result = _eval(
        RESERVE_CALL, [_session_key(token), _day_key("noaa")],
        settings.intelligence_demo_daily_noaa_budget, DAY_TTL,
    )
    if result == -1:
        raise HTTPException(401, "Demo session expired or invalid. Accept the notice again.")
    if result == -2:
        raise HTTPException(429, "This demo session has used its five requests.")
    if result == -3:
        raise HTTPException(503, "Today's public demo data budget has been reached.")
    if not 0 <= result < SESSION_QUOTA:
        raise HTTPException(503, "The public demo is temporarily unavailable.")
    return result
