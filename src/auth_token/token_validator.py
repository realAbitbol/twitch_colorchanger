"""Token validation logic."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..constants import (
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from .client import TokenOutcome

if TYPE_CHECKING:
    from .manager import TokenInfo, TokenManager


class TokenValidator:
    """Handles token validation operations."""

    def __init__(self, manager: TokenManager) -> None:
        self.manager = manager

    async def validate(self, username: str) -> TokenOutcome:
        """Validate a user's access token remotely.

        Args:
            username: Username to validate token for.

        Returns:
            VALID if token is valid, FAILED otherwise.

        Raises:
            aiohttp.ClientError: If network request fails.
            ValueError: If token data is invalid.
            RuntimeError: If validation process fails.
        """
        async with self.manager._tokens_lock:
            info = self.manager.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED
        now = time.time()
        if now - info.last_validation < TOKEN_MANAGER_VALIDATION_MIN_INTERVAL:
            return TokenOutcome.VALID
        if not info.expiry:
            return TokenOutcome.FAILED
        client = await self.manager.client_cache.get_client(info.client_id, info.client_secret)
        valid, expiry = await client._validate_remote(  # noqa: SLF001
            username, info.access_token
        )
        info.last_validation = now
        if valid:
            info.expiry = expiry
            return TokenOutcome.VALID
        return TokenOutcome.FAILED

    def remaining_seconds(self, info: TokenInfo) -> float | None:
        """Calculate remaining seconds until token expiry.

        Args:
            info: TokenInfo object containing expiry information.

        Returns:
            Remaining seconds as float, or None if expiry is unknown.
        """
        if not info.expiry:
            return None
        return (info.expiry - datetime.now(UTC)).total_seconds()

    def assess_token_health(self, info: TokenInfo, remaining: float | None, drift: float) -> str:
        """Assess token health status for proactive monitoring.

        Args:
            info: TokenInfo object containing token details.
            remaining: Remaining seconds until expiry.
            drift: Current drift in seconds.

        Returns:
            Health status: "healthy", "degraded", or "critical".
        """
        if remaining is None:
            # Unknown expiry is always degraded
            return "degraded"

        # Critical if token is expired or very close to expiry with drift
        if remaining <= 0 or (remaining <= 300 and drift > 60):
            return "critical"

        # Degraded if approaching expiry threshold with significant drift
        if remaining <= TOKEN_REFRESH_THRESHOLD_SECONDS and drift > 30:
            return "degraded"

        return "healthy"
