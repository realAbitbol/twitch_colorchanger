"""Adaptive backoff strategy extracted from rate_limiter for clarity."""

from __future__ import annotations

import logging
import time
from random import SystemRandom


class AdaptiveBackoff:
    def __init__(self) -> None:
        self._delay = 0.0
        self._until = 0.0
        self._last_unknown = 0.0
        self._count = 0
        self._rng = SystemRandom()

    # (Removed deprecated typing.Dict import per Ruff UP035)

    def snapshot(self) -> dict[str, float | int]:  # pragma: no cover (simple accessor)
        return {
            "delay": self._delay,
            "until": self._until,
            "remaining": max(0.0, self._until - time.time()),
            "count": self._count,
        }

    def active_delay(self) -> float:
        now = time.time()
        if self._until > now:
            return self._until - now
        return 0.0

    def reset(self) -> None:
        if self._delay > 0:
            logging.debug("♻️ Adaptive backoff reset")
        self._delay = 0.0
        self._until = 0.0
        self._count = 0

    def increase(self) -> None:
        now = time.time()
        if now - self._last_unknown > 60:
            self._count = 0
            self._delay = 0
        self._last_unknown = now
        self._count += 1
        if self._delay == 0:
            new_delay = 1.0
        else:
            new_delay = min(self._delay * 2, 30.0)
        jitter = new_delay * 0.1
        jittered = max(0.5, new_delay + self._rng.uniform(-jitter, jitter))
        self._delay = jittered
        self._until = now + self._delay
        level = logging.WARNING if self._delay >= 5 else logging.DEBUG
        logging.log(
            level,
            f"🔼 Adaptive backoff increased to {round(self._delay, 2)}s (count={self._count})",
        )
