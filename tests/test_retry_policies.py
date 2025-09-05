import asyncio
import logging
import time

import pytest

from src.errors.internal import InternalError
from src.rate.retry_policies import RetryPolicy, run_with_retry


@pytest.mark.asyncio
async def test_run_with_retry_success_on_second_attempt(caplog):
    """Operation succeeds on 2nd attempt; should log one attempt (no give up)."""
    caplog.set_level(logging.DEBUG)
    attempts = 0

    async def op():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise InternalError("transient")
        await asyncio.sleep(0)  # exercise async path
        return "ok"

    policy = RetryPolicy(
        name="test", max_attempts=3, base_delay=0.01, multiplier=2.0, max_delay=0.05, jitter=0
    )
    start = time.time()
    result = await run_with_retry(op, policy, user="u1")
    elapsed = time.time() - start
    assert result == "ok"
    assert attempts == 2
    msgs = [r.message for r in caplog.records]
    # An 'attempt' log must exist but no 'give up'. Fallback message uses 'retry: attempt'.
    assert any("attempt" in m for m in msgs)
    assert not any("give up" in m for m in msgs)
    assert elapsed >= 0.009  # base_delay minus small scheduling jitter


@pytest.mark.asyncio
async def test_run_with_retry_give_up_logs(caplog):
    """Operation always fails; expect attempt then give up logs."""
    caplog.set_level(logging.DEBUG)

    async def op():  # always fails
        await asyncio.sleep(0)
        raise InternalError("always")

    policy = RetryPolicy(
        name="fail", max_attempts=2, base_delay=0.01, multiplier=2.0, max_delay=0.02, jitter=0
    )
    with pytest.raises(InternalError):
        await run_with_retry(op, policy, user="u2")
    msgs = [r.message for r in caplog.records]
    assert any("attempt" in m for m in msgs)
    assert any("give up" in m for m in msgs)


def test_jitter_bounds():
    policy = RetryPolicy(
        name="jit", max_attempts=1, base_delay=1.0, multiplier=2.0, max_delay=10, jitter=0.5
    )
    samples = [policy.compute_delay(0) for _ in range(200)]
    # Base delay =1, jitter 0.5 -> expected approx range [0.5, 1.5]
    assert all(0.0 <= s <= 1.5 for s in samples)
    assert any(s < 0.75 for s in samples)
    assert any(s > 1.25 for s in samples)


def test_max_delay_cap():
    policy = RetryPolicy(
        name="cap", max_attempts=1, base_delay=5.0, multiplier=10.0, max_delay=3.0, jitter=0
    )
    assert abs(policy.compute_delay(2) - 3.0) < 1e-9
