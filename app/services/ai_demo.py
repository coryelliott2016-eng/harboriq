"""Anonymous demo safety boundary. No AI provider, database, tenant, or tools."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from functools import lru_cache

import redis
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.core.config import settings

UNAVAILABLE_MESSAGE = "The AI demo is unavailable because an AI engine is not configured."

# Check and charge every applicable quota together. Denied calls do not create
# partial charges; all new keys get TTLs in the same Redis operation.
_QUOTA_SCRIPT = """
local retry = 0
for i, key in ipairs(KEYS) do
    local count = tonumber(redis.call('GET', key) or '0')
    if count >= tonumber(ARGV[2 * i - 1]) then
        retry = math.max(retry, redis.call('TTL', key), 1)
    end
end
if retry > 0 then return retry end
for i, key in ipairs(KEYS) do
    redis.call('INCR', key)
    if redis.call('TTL', key) < 0 then
        redis.call('EXPIRE', key, tonumber(ARGV[2 * i]))
    end
end
return 0
"""


@lru_cache(maxsize=1)
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _secret() -> bytes:
    secret = settings.ai_demo_secret.encode()
    if len(secret) < 32 or settings.ai_demo_secret == settings.jwt_secret:
        raise HTTPException(503, "The AI demo safety configuration is unavailable.")
    return secret


def _mac(purpose: str, value: str) -> str:
    return hmac.new(_secret(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def ip_hash(request: Request) -> str:
    # Never trust caller-controlled forwarding headers. Configure trusted proxy
    # handling at the ASGI server if deploying behind a proxy.
    if request.client is None:
        raise HTTPException(503, "The AI demo client address is unavailable.")
    return _mac("ai-demo-ip-v1", request.client.host)


def _enforce_quotas(quotas: list[tuple[str, int, int]]) -> None:
    keys = [f"harboriq:{{ai-demo}}:v1:{key}" for key, _, _ in quotas]
    args = [value for _, limit, ttl in quotas for value in (limit, ttl)]
    try:
        retry = int(_redis_client().eval(_QUOTA_SCRIPT, len(keys), *keys, *args))
    except (RedisError, ValueError, TypeError):
        raise HTTPException(503, "The AI demo safety service is unavailable.") from None
    if retry:
        raise HTTPException(
            429, "AI demo request limit reached.", headers={"Retry-After": str(max(1, retry))}
        )


def mint_session(request: Request) -> str:
    address = ip_hash(request)
    _enforce_quotas([
        (
            f"mint:{address}",
            settings.ai_demo_session_mints_per_ip,
            settings.ai_demo_rate_window_seconds,
        )
    ])
    value = f"{secrets.token_hex(32)}.{int(time.time()) + settings.ai_demo_session_ttl_seconds}"
    return f"{value}.{_mac('ai-demo-session-v1', value)}"


def validate_session(token: str) -> tuple[str, int]:
    _secret()
    if not re.fullmatch(r"[0-9a-f]{64}\.[0-9]{1,12}\.[0-9a-f]{64}", token):
        raise HTTPException(401, "Invalid or expired demo session.")
    session_id, expires, signature = token.split(".")
    value = f"{session_id}.{expires}"
    if not hmac.compare_digest(signature, _mac("ai-demo-session-v1", value)):
        raise HTTPException(401, "Invalid or expired demo session.")
    ttl = int(expires) - int(time.time())
    if ttl <= 0:
        raise HTTPException(401, "Invalid or expired demo session.")
    return session_id, ttl


def enforce_chat_limits(request: Request, token: str) -> None:
    session_id, ttl = validate_session(token)
    address = ip_hash(request)
    window = settings.ai_demo_rate_window_seconds
    _enforce_quotas([
        (f"session:{session_id}", settings.ai_demo_message_limit, ttl),
        (f"chat-ip:{address}", settings.ai_demo_chat_requests_per_ip, window),
        ("chat-global", settings.ai_demo_chat_requests_global, window),
    ])
