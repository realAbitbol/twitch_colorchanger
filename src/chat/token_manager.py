"""TokenManager for EventSub chat backend operations.

This module provides a specialized TokenManager class that handles token validation,
scope recording, refresh coordination, and invalid token detection with callbacks
specifically for EventSub chat operations. It integrates with the existing token
management infrastructure while adding EventSub-specific error handling and scope validation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

from ..api.twitch import TwitchAPI
from ..auth_token.manager import TokenManager as GlobalTokenManager
from ..constants import EVENTSUB_CONSECUTIVE_401_THRESHOLD
from ..errors.eventsub import AuthenticationError, EventSubError
from .protocols import TokenManagerProtocol

# Required OAuth scopes for EventSub chat operations
REQUIRED_SCOPES = {"chat:read", "user:read:chat", "user:manage:chat_color"}


class TokenManager(TokenManagerProtocol):
    """Specialized token manager for EventSub chat backend operations.

    This class coordinates token validation, refresh operations, and scope management
    specifically for EventSub chat functionality. It integrates with the global TokenManager
    while providing EventSub-specific error handling and invalid token detection.

    Attributes:
        username: The username associated with the token.
        client_id: Twitch client ID.
        client_secret: Twitch client secret.
        http_session: HTTP session for API requests.
        token_manager: Global TokenManager instance.
        api: TwitchAPI client instance.
        recorded_scopes: Set of validated OAuth scopes.
        consecutive_401_count: Count of consecutive 401 errors.
        invalid_callback: Optional callback for token invalidation events.
    """

    def __init__(
        self,
        username: str,
        client_id: str,
        client_secret: str,
        http_session: aiohttp.ClientSession,
        token_manager: GlobalTokenManager | None = None,
    ) -> None:
        """Initialize the EventSub TokenManager.

        Args:
            username: Username associated with the token.
            client_id: Twitch client ID.
            client_secret: Twitch client secret.
            http_session: HTTP session for API requests.
            token_manager: Optional global TokenManager instance. If None, uses the singleton.

        Raises:
            ValueError: If required parameters are invalid.
        """
        if not username or not isinstance(username, str):
            raise ValueError("username must be a non-empty string")
        if not client_id or not isinstance(client_id, str):
            raise ValueError("client_id must be a non-empty string")
        if not client_secret or not isinstance(client_secret, str):
            raise ValueError("client_secret must be a non-empty string")
        if not http_session:
            raise ValueError("http_session cannot be None")

        self.username = username.lower()
        self.client_id = client_id
        self.client_secret = client_secret
        self.http_session = http_session
        self.token_manager = token_manager or GlobalTokenManager(http_session)
        self.api = TwitchAPI(http_session)

        # EventSub-specific state
        self.recorded_scopes: set[str] = set()
        self.consecutive_401_count = 0
        self.invalid_callback: Callable[[], Coroutine[Any, Any, None]] | None = None

    async def validate_token(self, access_token: str) -> bool:
        """Validate the access token and record its scopes.

        Performs remote validation of the token and extracts the granted OAuth scopes,
        storing them for later use in scope validation.

        Args:
            access_token: The access token to validate.

        Returns:
            True if token is valid and scopes recorded, False otherwise.

        Raises:
            AuthenticationError: If token validation fails.
            EventSubError: If validation process encounters an error.
        """
        if not access_token:
            return False

        try:
            validation = await self.api.validate_token(access_token)
            if not isinstance(validation, dict):
                logging.warning(
                    f"🚫 Token validation failed for user {self.username}: invalid response"
                )
                return False

            raw_scopes = validation.get("scopes")
            if not isinstance(raw_scopes, list):
                logging.warning(
                    f"🚫 Token validation failed for user {self.username}: no scopes in response"
                )
                return False

            # Record scopes in lowercase for consistent comparison
            self.recorded_scopes = {str(scope).lower() for scope in raw_scopes}
            logging.debug(
                f"🧪 Token scopes recorded for user {self.username}: {';'.join(sorted(self.recorded_scopes))}"
            )
            return True

        except aiohttp.ClientError as e:
            raise AuthenticationError(
                f"Token validation network error for user {self.username}: {str(e)}",
                user_id=self.username,
                operation_type="validate_token",
            ) from e
        except Exception as e:
            raise EventSubError(
                f"Token validation error for user {self.username}: {str(e)}",
                user_id=self.username,
                operation_type="validate_token",
            ) from e

    async def refresh_token(self, force_refresh: bool = False) -> bool:
        """Coordinate token refresh operation.

        Uses the global TokenManager to ensure the token is fresh, then re-validates
        scopes after refresh.

        Args:
            force_refresh: Force refresh regardless of token expiry.

        Returns:
            True if refresh successful and scopes validated, False otherwise.

        Raises:
            AuthenticationError: If refresh fails.
            EventSubError: If refresh process encounters an error.
        """
        try:
            # Use global TokenManager for refresh
            outcome = await self.token_manager.ensure_fresh(
                self.username, force_refresh
            )
            if outcome.name == "FAILED":
                logging.error(f"🚫 Token refresh failed for user {self.username}")
                return False

            # Get updated token info
            info = await self.token_manager.get_info(self.username)
            if not info or not info.access_token:
                logging.error(
                    f"🚫 No token info after refresh for user {self.username}"
                )
                return False

            # Re-validate and record scopes
            if await self.validate_token(info.access_token):
                logging.info(
                    f"✅ Token refreshed and validated for user {self.username}"
                )
                return True
            else:
                logging.warning(
                    f"⚠️ Token refresh succeeded but scope validation failed for user {self.username}"
                )
                return False

        except Exception as e:
            if isinstance(e, AuthenticationError | EventSubError):
                raise
            raise EventSubError(
                f"Token refresh coordination error for user {self.username}: {str(e)}",
                user_id=self.username,
                operation_type="refresh_token",
            ) from e

    def check_scopes(self) -> bool:
        """Validate that all required scopes are present.

        Checks if the recorded scopes include all required scopes for EventSub chat operations.

        Returns:
            True if all required scopes are present, False otherwise.
        """
        missing = REQUIRED_SCOPES - self.recorded_scopes
        if missing:
            logging.warning(
                f"🚫 Missing required scopes for user {self.username}: {';'.join(sorted(missing))}"
            )
            return False
        return True

    def set_invalid_callback(
        self, callback: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for token invalidation events.

        The callback will be invoked when the token is detected as invalid
        (e.g., after consecutive 401 errors).

        Args:
            callback: Async callable to invoke on token invalidation.
        """
        self.invalid_callback = callback

    async def handle_401_error(self) -> None:
        """Handle a 401 Unauthorized error with threshold-based invalidation.

        Increments the consecutive 401 counter and triggers invalidation
        if the threshold is exceeded.

        Raises:
            AuthenticationError: If token is invalidated due to threshold.
        """
        self.consecutive_401_count += 1
        logging.warning(
            f"🚫 EventSub 401 error for user {self.username}, count={self.consecutive_401_count}"
        )

        if self.consecutive_401_count >= EVENTSUB_CONSECUTIVE_401_THRESHOLD:
            logging.error(
                f"🚫 Token invalidated for user {self.username} due to {self.consecutive_401_count} consecutive 401 errors"
            )
            # Reset counter
            self.consecutive_401_count = 0
            # Trigger invalidation callback
            if self.invalid_callback:
                try:
                    await self.invalid_callback()
                except Exception as e:
                    logging.warning(
                        f"⚠️ Error in token invalid callback for user {self.username}: {str(e)}"
                    )
            # Raise authentication error
            raise AuthenticationError(
                f"Token invalidated after {EVENTSUB_CONSECUTIVE_401_THRESHOLD} consecutive 401 errors",
                user_id=self.username,
                operation_type="handle_401",
            )

    def get_scopes(self) -> set[str]:
        """Get the currently recorded OAuth scopes.

        Returns:
            Set of recorded scopes.
        """
        return self.recorded_scopes.copy()

    async def is_token_valid(self) -> bool:
        """Check if the current token is valid and has required scopes.

        Performs validation and scope checking.

        Returns:
            True if token is valid and has required scopes, False otherwise.
        """
        try:
            info = await self.token_manager.get_info(self.username)
            if not info or not info.access_token:
                return False

            # Validate token and record scopes
            if not await self.validate_token(info.access_token):
                return False

            # Check scopes
            return self.check_scopes()

        except Exception as e:
            logging.debug(
                f"⚠️ Token validity check error for user {self.username}: {str(e)}"
            )
            return False

    def reset_401_counter(self) -> None:
        """Reset the consecutive 401 error counter.

        Should be called when a successful operation occurs.
        """
        if self.consecutive_401_count > 0:
            logging.debug(f"🔄 Reset 401 counter for user {self.username}")
            self.consecutive_401_count = 0

    async def ensure_valid_token(self) -> str | None:
        """Ensure the token is valid and return it.

        Performs validation, refresh if needed, and scope checking.

        Returns:
            The valid access token, or None if validation/refresh fails.
        """
        if not await self.is_token_valid():
            # Try refresh
            if not await self.refresh_token():
                return None

            # Re-check after refresh
            if not await self.is_token_valid():
                return None

        # Get the token
        info = await self.token_manager.get_info(self.username)
        return info.access_token if info else None

    async def __aenter__(self) -> TokenManager:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        # No specific cleanup needed for TokenManager
        pass
