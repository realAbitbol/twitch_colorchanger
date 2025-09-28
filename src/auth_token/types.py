"""Shared types and constants for auth_token module."""

from enum import Enum
from secrets import SystemRandom

_jitter_rng = SystemRandom()


class TokenState(Enum):
    """Enumeration of token freshness states.

    Attributes:
        FRESH: Token is recently obtained or refreshed.
        STALE: Token is valid but nearing expiry.
        EXPIRED: Token has expired and needs refresh.
    """

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
