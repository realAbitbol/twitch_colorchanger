import time

import pytest

from src.rate.rate_limiter import RateLimitInfo, TwitchRateLimiter


def make_bucket(limit: int, remaining: int, reset_in: float) -> RateLimitInfo:
    now = time.time()
    return RateLimitInfo(
        limit=limit,
        remaining=remaining,
        reset_timestamp=now + reset_in,
        last_updated=now,
        monotonic_last_updated=time.monotonic(),
    )


@pytest.mark.asyncio
async def test_wait_no_bucket_min_delay(monkeypatch):
    rl = TwitchRateLimiter("cid", "user")
    # Speed up by forcing min_delay small
    rl.min_delay = 0
    start = time.time()
    await rl.wait_if_needed("endpoint", is_user_request=True)
    assert time.time() - start < 0.05


@pytest.mark.asyncio
async def test_wait_immediate_when_remaining_above_buffer():
    rl = TwitchRateLimiter("cid", "user")
    rl.user_bucket = make_bucket(limit=100, remaining=90, reset_in=30)
    rl.safety_buffer = 5
    start = time.time()
    await rl.wait_if_needed("x", is_user_request=True)
    assert time.time() - start < 0.02
    assert rl.user_bucket.remaining == 89  # decremented


@pytest.mark.asyncio
async def test_wait_brief_delay_when_close_to_buffer():
    rl = TwitchRateLimiter("cid", "user")
    rl.min_delay = 0.01
    rl.user_bucket = make_bucket(limit=100, remaining=6, reset_in=20)
    rl.safety_buffer = 5
    start = time.time()
    await rl.wait_if_needed("x", is_user_request=True)
    elapsed = time.time() - start
    # remaining (6) >= points_needed(1)+safety_buffer(5) -> no delay expected
    assert elapsed < 0.005
    assert rl.user_bucket.remaining == 5


@pytest.mark.asyncio
async def test_wait_until_reset_when_out_of_points():
    rl = TwitchRateLimiter("cid", "user")
    rl.user_bucket = make_bucket(limit=100, remaining=0, reset_in=0.05)
    start = time.time()
    await rl.wait_if_needed("x", is_user_request=True)
    elapsed = time.time() - start
    assert elapsed >= 0.04  # had to wait for reset window


def test_handle_429_sets_bucket():
    rl = TwitchRateLimiter("cid", "user")
    future_reset = time.time() + 10
    rl.handle_429_error({"ratelimit-reset": str(future_reset)}, is_user_request=True)
    assert rl.user_bucket is not None
    assert rl.user_bucket.remaining == 0
    assert abs(rl.user_bucket.reset_timestamp - future_reset) < 0.01


def test_backoff_increase_and_reset(monkeypatch):
    rl = TwitchRateLimiter("cid")
    # Force unknown reset path (no reset header)
    rl.handle_429_error({}, is_user_request=False)
    d1 = rl._backoff.active_delay()
    assert d1 > 0
    # Second increase grows delay
    rl.handle_429_error({}, is_user_request=False)
    d2 = rl._backoff.active_delay()
    assert d2 >= d1
    # Provide reset header -> should reset backoff
    future_reset = time.time() + 5
    rl.handle_429_error({"ratelimit-reset": str(future_reset)}, is_user_request=False)
    assert rl._backoff.active_delay() == 0


def test_conservative_mode_hysteresis():
    rl = TwitchRateLimiter("cid", "user")
    rl.user_bucket = make_bucket(limit=100, remaining=5, reset_in=30)
    rl.safety_buffer = 5
    # Trigger conservative entry via private method to isolate logic
    eff = rl._update_conservative_mode(rl.user_bucket, points_needed=1)
    assert rl.is_conservative_mode is True
    assert eff == rl.safety_buffer + rl.hysteresis_threshold
    # Raise remaining above exit threshold
    # Need remaining > (effective_safety_buffer + points_needed + 5)
    # effective_safety_buffer while in conservative = safety_buffer + hysteresis_threshold = 5 + 10 = 15
    # Threshold = 15 + 1 + 5 = 21, so set to 25 to be safely above
    rl.user_bucket.remaining = 25
    eff2 = rl._update_conservative_mode(rl.user_bucket, points_needed=1)
    assert rl.is_conservative_mode is False
    assert eff2 == rl.safety_buffer
