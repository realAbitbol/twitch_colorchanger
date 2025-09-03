"""Retry policy abstraction.

Provides a declarative way to describe retry behaviour and a helper to execute
an async operation under that policy. Central event logging is performed here
so callers don't duplicate per-attempt logging.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from random import SystemRandom
from typing import TypeVar

from ..errors.internal import InternalError
from ..logs.logger import logger

_rand = SystemRandom()


@dataclass(slots=True)
class RetryPolicy:
    name: str
    max_attempts: int = 3
    base_delay: float = 0.5
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.25  # fraction ± of computed delay
    retriable: Sequence[type[BaseException]] = (InternalError,)

    def compute_delay(self, attempt_index: int) -> float:
        delay = self.base_delay * (self.multiplier**attempt_index)
        delay = min(delay, self.max_delay)
        if self.jitter > 0:
            spread = delay * self.jitter
            delay += _rand.uniform(-spread, spread)
            if delay < 0:
                delay = 0
        return delay

    def is_retriable(self, exc: BaseException) -> bool:
        return any(isinstance(exc, t) for t in self.retriable)


T = TypeVar("T")


async def run_with_retry(
    operation: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    user: str | None = None,
    log_domain: str = "retry",
    log_action_attempt: str = "attempt",
    log_action_give_up: str = "give_up",
) -> T:
    """Run an async operation under a retry policy.

    Emits structured events for each attempt and final give-up.
    """

    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except Exception as e:  # noqa: BLE001
            last_error = e
            retriable = policy.is_retriable(e)
            if attempt == policy.max_attempts or not retriable:
                logger.log_event(
                    log_domain,
                    log_action_give_up,
                    level=logging.ERROR,
                    attempt=attempt,
                    max_attempts=policy.max_attempts,
                    user=user,
                    error=str(e),
                    error_type=type(e).__name__,
                    retriable=retriable,
                )
                raise
            delay = policy.compute_delay(attempt - 1)
            logger.log_event(
                log_domain,
                log_action_attempt,
                level=logging.WARNING,
                attempt=attempt,
                max_attempts=policy.max_attempts,
                wait_time=round(delay, 3),
                user=user,
                error=str(e),
                error_type=type(e).__name__,
            )
            await asyncio.sleep(delay)
    # Should not reach here
    if last_error:
        raise last_error
    raise RuntimeError("run_with_retry completed without result or error")


# Predefined common policies (can be imported and used directly)
DEFAULT_NETWORK_RETRY = RetryPolicy(
    name="network_default", max_attempts=4, base_delay=0.5, multiplier=2.0, max_delay=10
)

TOKEN_REFRESH_RETRY = RetryPolicy(
    name="token_refresh", max_attempts=3, base_delay=1.0, multiplier=2.0, max_delay=15
)

# Color change network retry (lightweight, focuses on transient network hiccups)
COLOR_CHANGE_RETRY = RetryPolicy(
    name="color_change", max_attempts=3, base_delay=0.3, multiplier=2.0, max_delay=3
)

__all__ = [
    "RetryPolicy",
    "run_with_retry",
    "DEFAULT_NETWORK_RETRY",
    "TOKEN_REFRESH_RETRY",
    "COLOR_CHANGE_RETRY",
]
