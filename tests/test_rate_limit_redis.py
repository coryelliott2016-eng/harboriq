"""Redis-backed rate limiter (Phase 16).

`app/core/rate_limit.py` moved from an in-process dict to Redis specifically
so multiple app processes/pods enforce ONE shared limit rather than each
having its own private counter. The whole point of the swap is proven here
by simulating two separate "instances" (two independent limiter objects,
each with its own Python-level state, both pointed at the same Redis key)
and showing a client is throttled based on the SUM of hits across both, not
reset by which instance happens to handle a given request.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.rate_limit import _RedisFixedWindowLimiter, _reset_all_for_tests


def setup_function(_):
    _reset_all_for_tests()


def teardown_function(_):
    _reset_all_for_tests()


def test_two_simulated_instances_share_one_redis_backed_counter():
    """Two independent limiter instances (simulating two app processes) must
    enforce the SAME budget for the same client identity, because both read
    and write the same Redis key rather than private in-process state."""
    limit = settings.rate_limit_requests_per_window
    window = settings.rate_limit_window_seconds

    # Two distinct Python objects, as if constructed independently by two
    # separate uvicorn worker processes -- no shared Python state between
    # them, only the same Redis bucket name/key namespace.
    instance_a = _RedisFixedWindowLimiter("login", limit, window)
    instance_b = _RedisFixedWindowLimiter("login", limit, window)

    client_ip = "203.0.113.7"

    # Alternate hits between the two "instances". If they were still
    # in-process (pre-Phase-16 behavior), each would allow up to `limit`
    # requests independently -- 2x the real budget across both. With a
    # shared Redis counter, the combined total across both instances must
    # still cap out at exactly `limit`.
    allowed_count = 0
    for i in range(limit + 5):
        instance = instance_a if i % 2 == 0 else instance_b
        allowed, retry_after = instance.hit(client_ip)
        if allowed:
            allowed_count += 1
        else:
            assert retry_after > 0

    assert allowed_count == limit


def test_a_hit_on_instance_b_is_immediately_visible_to_instance_a():
    """The very next hit on a DIFFERENT limiter object must see the prior
    instance's count, proving there is no per-instance caching involved."""
    limit = settings.rate_limit_requests_per_window
    window = settings.rate_limit_window_seconds
    instance_a = _RedisFixedWindowLimiter("login", limit, window)
    instance_b = _RedisFixedWindowLimiter("login", limit, window)
    client_ip = "203.0.113.8"

    # Exhaust the budget entirely on instance_a.
    for _ in range(limit):
        allowed, _ = instance_a.hit(client_ip)
        assert allowed

    # instance_b, which has never seen this IP before in its own (nonexistent)
    # local state, must still see the client as over budget.
    allowed, retry_after = instance_b.hit(client_ip)
    assert not allowed
    assert retry_after > 0


def test_different_buckets_do_not_share_a_counter():
    """Login and password-reset buckets remain independently budgeted even
    though both live in the same Redis instance."""
    limit = settings.rate_limit_requests_per_window
    window = settings.rate_limit_window_seconds
    login_limiter = _RedisFixedWindowLimiter("login", limit, window)
    reset_limiter = _RedisFixedWindowLimiter("password_reset", limit, window)
    client_ip = "203.0.113.9"

    for _ in range(limit):
        allowed, _ = login_limiter.hit(client_ip)
        assert allowed

    allowed, _ = login_limiter.hit(client_ip)
    assert not allowed

    # The password-reset bucket for the same IP is untouched.
    allowed, _ = reset_limiter.hit(client_ip)
    assert allowed


def test_reset_clears_the_shared_counter():
    limit = settings.rate_limit_requests_per_window
    window = settings.rate_limit_window_seconds
    limiter = _RedisFixedWindowLimiter("login", limit, window)
    client_ip = "203.0.113.10"

    for _ in range(limit):
        limiter.hit(client_ip)
    allowed, _ = limiter.hit(client_ip)
    assert not allowed

    limiter.reset()

    allowed, _ = limiter.hit(client_ip)
    assert allowed
