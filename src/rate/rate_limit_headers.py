"""Header parsing utilities for Twitch rate limiting.

Separated from core limiter to allow isolated testing and reuse.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class ParsedRateLimit:
    limit: int
    remaining: int
    reset_timestamp: float
    last_updated: float
    monotonic_last_updated: float


def parse_rate_limit_headers(headers: Mapping[str, str]) -> ParsedRateLimit | None:
    """Parse Twitch Helix rate limit headers.

    Returns None if incomplete.
    """

    # Case-insensitive access attempt
    def get_ci(name: str) -> str | None:
        return (
            headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())
        )

    limit = get_ci("ratelimit-limit")
    remaining = get_ci("ratelimit-remaining")
    reset = get_ci("ratelimit-reset")
    if limit and remaining and reset:
        now = time.time()
        return ParsedRateLimit(
            limit=int(limit),
            remaining=int(remaining),
            reset_timestamp=float(reset),
            last_updated=now,
            monotonic_last_updated=time.monotonic(),
        )
    return None
