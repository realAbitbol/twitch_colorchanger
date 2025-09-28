"""Token refresh logic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..constants import TOKEN_REFRESH_THRESHOLD_SECONDS
from .client import RefreshErrorType, TokenClient, TokenOutcome, TokenResult
from .types import TokenState

if TYPE_CHECKING:
    from .manager import TokenInfo, TokenManager


class TokenRefresher:
    """Handles token refresh operations."""

    def __init__(self, manager: TokenManager) -> None:
        self.manager = manager

    async def ensure_fresh(
        self, username: str, force_refresh: bool = False
    ) -> TokenOutcome:
        """Ensure the user's token is fresh, refreshing if necessary.

        Args:
            username: Username to check/refresh token for.
            force_refresh: Force refresh regardless of expiry.

        Returns:
            Outcome of the ensure fresh operation.

        Raises:
            aiohttp.ClientError: If network requests fail.
            ValueError: If token data is invalid.
            RuntimeError: If refresh process fails.
        """
        async with self.manager._tokens_lock:
            info = self.manager.tokens.get(username)
            if not info:
                return TokenOutcome.FAILED

            if self._should_skip_refresh(info, force_refresh):
                return TokenOutcome.VALID

            client = await self.manager.client_cache.get_client(info.client_id, info.client_secret)
            result, _ = await self._refresh_with_lock(
                client, info, username, force_refresh
            )
            return result.outcome

    def _should_skip_refresh(self, info: TokenInfo, force_refresh: bool) -> bool:
        """Determine if token refresh should be skipped.

        Skips if not forced and expiry exists with sufficient remaining time.

        Args:
            info: TokenInfo object containing token details.
            force_refresh: Whether to force refresh regardless of expiry.

        Returns:
            True if refresh should be skipped, False otherwise.
        """
        if force_refresh:
            return False
        remaining = self.manager.validator.remaining_seconds(info)
        return (
            bool(info.expiry)
            and remaining is not None
            and remaining > TOKEN_REFRESH_THRESHOLD_SECONDS
        )

    async def _refresh_with_lock(
        self,
        client: TokenClient,
        info: TokenInfo,
        username: str,
        force_refresh: bool,
    ) -> tuple[TokenResult, bool]:
        """Perform token refresh with locking to prevent concurrency issues.

        Ensures only one refresh operation per user at a time.

        Args:
            client: TokenClient to use for refresh.
            info: TokenInfo object containing token details.
            username: Username associated with the token.
            force_refresh: Whether to force refresh.

        Returns:
            Tuple of (TokenResult from refresh, whether token actually changed).
        """
        token_changed = False
        async with info.refresh_lock:
            before_access = info.access_token
            before_refresh = info.refresh_token
            result = await client.ensure_fresh(
                username,
                info.access_token,
                info.refresh_token,
                info.expiry,
                force_refresh,
            )
            if result.outcome != TokenOutcome.FAILED and result.access_token:
                self._apply_successful_refresh(info, result)
                token_changed = (
                    info.access_token != before_access
                    or info.refresh_token != before_refresh
                )
            elif result.outcome == TokenOutcome.FAILED:
                if result.error_type == RefreshErrorType.NON_RECOVERABLE:
                    info.state = TokenState.EXPIRED
                    # Fire invalidation hook for non-recoverable refresh failures
                    await self.manager.hook_manager.maybe_fire_invalidation_hook(username)
        # Fire hook if token actually changed. This is the single authoritative
        # location for firing update hooks to avoid double invocation (the
        # ensure_fresh wrapper deliberately does NOT fire the hook).
        await self.manager.hook_manager.maybe_fire_update_hook(username, token_changed)
        return result, token_changed

    def _apply_successful_refresh(self, info: TokenInfo, result: TokenResult) -> None:
        """Apply the results of a successful token refresh to TokenInfo.

        Updates access token, refresh token, expiry, and state.

        Args:
            info: TokenInfo object to update.
            result: TokenResult containing refresh outcome data.
        """
        if result.access_token is not None:
            info.access_token = result.access_token
        if result.refresh_token:
            info.refresh_token = result.refresh_token
        info.expiry = result.expiry
        info.state = (
            TokenState.FRESH
            if result.outcome in (TokenOutcome.VALID, TokenOutcome.SKIPPED)
            else TokenState.STALE
        )
        # If we actually performed a refresh (new token lifetime), reset baseline.
        if result.outcome == TokenOutcome.REFRESHED and info.expiry:
            remaining = int((info.expiry - datetime.now(UTC)).total_seconds())
            if remaining > 0:
                info.original_lifetime = remaining
