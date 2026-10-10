"""Consent-gated aggregate counters only: no individual events or metadata."""
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas.marketing_events import MarketingEvent
from app.services import ai_demo

# Quotas and the aggregate increment are one operation. Keys share a Redis
# Cluster hash slot; no denial/outage can fall back to individual event storage.
_EVENT_SCRIPT = """
local retry = 0
for i = 1, 2 do
    local count = tonumber(redis.call('GET', KEYS[i]) or '0')
    if count >= tonumber(ARGV[2 * i - 1]) then
        retry = math.max(retry, redis.call('TTL', KEYS[i]), 1)
    end
end
if retry > 0 then return retry end
for i = 1, 2 do
    redis.call('INCR', KEYS[i])
    if redis.call('TTL', KEYS[i]) < 0 then
        redis.call('EXPIRE', KEYS[i], tonumber(ARGV[2 * i]))
    end
end
redis.call('INCR', KEYS[3])
local ttl = redis.call('TTL', KEYS[3])
if ttl < 0 or ttl > tonumber(ARGV[5]) then
    redis.call('EXPIRE', KEYS[3], tonumber(ARGV[5]))
end
return 0
"""


def count_event(request: Request, event: MarketingEvent) -> None:
    if request.client is None:
        raise HTTPException(503, "Analytics safety service is unavailable.")
    try:
        address = ai_demo._mac("marketing-events-ip-v1", request.client.host)
    except HTTPException:
        raise HTTPException(503, "Analytics safety configuration is unavailable.") from None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = "harboriq:{marketing-events}:v1"
    keys = [
        f"{prefix}:limit:ip:{address}",
        f"{prefix}:limit:global",
        f"{prefix}:daily:{day}:{event}",
    ]
    window = settings.marketing_events_window_seconds
    args = [
        settings.marketing_events_requests_per_ip, window,
        settings.marketing_events_requests_global, window,
        settings.marketing_events_retention_days * 86400,
    ]
    try:
        retry = int(ai_demo._redis_client().eval(_EVENT_SCRIPT, 3, *keys, *args))
    except (RedisError, ValueError, TypeError):
        raise HTTPException(503, "Analytics safety service is unavailable.") from None
    if retry:
        raise HTTPException(
            429, "Analytics request limit reached.", headers={"Retry-After": str(max(1, retry))}
        )
