"""Token validation / refresh HTTP client (moved from token_client.py)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import aiohttp

from ..constants import (
    TOKEN_REFRESH_SAFETY_BUFFER_SECONDS,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from ..errors.internal import NetworkError, OAuthError, ParsingError, RateLimitError
from ..utils import format_duration


class TokenOutcome(str, Enum):
    """Enumeration of possible outcomes from token validation or refresh operations.

    Attributes:
        VALID: Token is valid and does not need refresh.
        REFRESHED: Token was successfully refreshed.
        SKIPPED: No action needed as token is within safe threshold.
        FAILED: Operation failed.
    """

    VALID = "valid"
    REFRESHED = "refreshed"
    SKIPPED = "skipped"  # no action needed; still within safe threshold
    FAILED = "failed"


@dataclass
class TokenResult:
    """Result of a token validation or refresh operation.

    Attributes:
        outcome: The outcome of the operation.
        access_token: The access token, if available.
        refresh_token: The refresh token, if available.
        expiry: The expiry datetime, if available.
    """

    outcome: TokenOutcome
    access_token: str | None
    refresh_token: str | None
    expiry: datetime | None


class TokenClient:
    """Client for validating and refreshing Twitch OAuth tokens.

    Handles HTTP requests to Twitch's OAuth endpoints for token validation
    and refresh operations.
    """

    def __init__(
        self, client_id: str, client_secret: str, http_session: aiohttp.ClientSession
    ):
        """Initialize the token client.

        Args:
            client_id: Twitch application client ID.
            client_secret: Twitch application client secret.
            http_session: HTTP session for making requests.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = http_session

    async def validate(self, username: str, access_token: str) -> TokenResult:
        """Validate an access token remotely.

        Args:
            username: Username associated with the token.
            access_token: The access token to validate.

        Returns:
            TokenResult with VALID outcome if token is valid, FAILED otherwise.
        """
        valid, expiry = await self._validate_remote(username, access_token)
        if valid:
            return TokenResult(TokenOutcome.VALID, access_token, None, expiry)
        return TokenResult(TokenOutcome.FAILED, None, None, None)

    async def ensure_fresh(
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        """Ensure the token is fresh, refreshing if necessary.

        Checks if refresh is needed based on expiry and threshold, validates
        remotely if not forced, and refreshes if required.

        Args:
            username: Username associated with the token.
            access_token: Current access token.
            refresh_token: Refresh token, if available.
            expiry: Known expiry datetime.
            force_refresh: Force refresh regardless of expiry.

        Returns:
            TokenResult with outcome of the operation.
        """
        # Skip if not forced and expiry is far enough in the future
        if (
            not force_refresh
            and expiry
            and (expiry - datetime.now(UTC)).total_seconds()
            > TOKEN_REFRESH_THRESHOLD_SECONDS
        ):
            return TokenResult(
                TokenOutcome.SKIPPED, access_token, refresh_token, expiry
            )

        # If not forced, validate remotely first
        if not force_refresh:
            is_valid, remote_expiry = await self._validate_remote(
                username, access_token
            )
            if is_valid:
                final_expiry = remote_expiry or expiry
                # Check if still within threshold after validation
                if (
                    final_expiry
                    and (final_expiry - datetime.now(UTC)).total_seconds()
                    > TOKEN_REFRESH_THRESHOLD_SECONDS
                ):
                    return TokenResult(
                        TokenOutcome.SKIPPED,
                        access_token,
                        refresh_token,
                        final_expiry,
                    )
                logging.warning(
                    f"⏳ Token valid but expiring soon - scheduling refresh user={username}"
                )

        # Need refresh token to proceed
        if not refresh_token:
            return TokenResult(TokenOutcome.FAILED, None, None, expiry)
        return await self.refresh(username, refresh_token)

    async def refresh(self, username: str, refresh_token: str) -> TokenResult:
        """Refresh an access token using the refresh token.

        Makes a POST request to Twitch's token endpoint and parses the response.

        Args:
            username: Username associated with the token.
            refresh_token: The refresh token to use.

        Returns:
            TokenResult with REFRESHED outcome on success, FAILED on error.

        Raises:
            NetworkError: On network-related failures.
        """
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            url = "https://id.twitch.tv/oauth2/token"
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.session.post(url, data=data, timeout=timeout) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    new_access = js.get("access_token")
                    new_refresh = js.get("refresh_token", refresh_token)
                    expires_in = js.get("expires_in")
                    if not new_access:
                        raise ParsingError("Missing access_token in refresh response")
                    expiry = None
                    if expires_in:
                        # Apply safety buffer to avoid refreshing too late
                        safe_expires = max(
                            expires_in - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0
                        )
                        expiry = datetime.now(UTC) + timedelta(seconds=safe_expires)
                    human_expires = format_duration(expires_in)
                    logging.info(
                        f"Token refreshed (lifetime {human_expires}) user={username} attempt={1} expires_in={expires_in}"
                    )
                    return TokenResult(
                        TokenOutcome.REFRESHED, new_access, new_refresh, expiry
                    )
                if resp.status == 401:
                    raise OAuthError("Unauthorized during token refresh")
                if resp.status == 429:
                    raise RateLimitError("Rate limited during refresh")
                raise NetworkError(f"HTTP {resp.status} during token refresh")
        except TimeoutError as e:
            raise NetworkError("Token refresh timeout") from e
        except aiohttp.ClientError as e:
            raise NetworkError(f"Network error during token refresh: {e}") from e
        except ParsingError:
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except OAuthError:
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except RateLimitError:
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except NetworkError as e:
            logging.warning(
                f"💥 Network error during token refresh attempt 1: {type(e).__name__} user={username} error={str(e)}"
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except Exception as e:  # noqa: BLE001
            import traceback

            logging.error(
                f"💥 Unexpected token refresh error: {type(e).__name__} user={username} error={str(e)} traceback={traceback.format_exc()}"
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)

    async def _validate_remote(
        self, username: str, access_token: str
    ) -> tuple[bool, datetime | None]:
        """Validate token remotely via Twitch's validate endpoint.

        Args:
            username: Username associated with the token.
            access_token: Access token to validate.

        Returns:
            Tuple of (is_valid, expiry_datetime).
        """
        try:
            url = "https://id.twitch.tv/oauth2/validate"
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {"Authorization": f"OAuth {access_token}"}
            async with self.session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    expires_in = data.get("expires_in")
                    expiry = None
                    if expires_in:
                        # Apply safety buffer to match refresh logic and prevent late refreshes
                        safe_expires = max(
                            expires_in - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0
                        )
                        expiry = datetime.now(UTC) + timedelta(seconds=safe_expires)
                        logging.debug(
                            f"Token valid (remaining {format_duration(expires_in)} raw, buffered {format_duration(safe_expires)}) user={username} expires_in={expires_in} buffered_expires_in={safe_expires}"
                        )
                    return True, expiry
                if resp.status == 401:
                    # 401 indicates expired token; refresh will follow
                    logging.info(
                        f"❌ Token validation failed: invalid (status={resp.status}) user={username}"
                    )
                elif resp.status == 429:
                    logging.warning(
                        f"⏳ Token validation rate limited (status={resp.status}) user={username}"
                    )
                else:
                    logging.warning(
                        f"❌ Token validation failed (status={resp.status}) user={username}"
                    )
                return False, None
        except TimeoutError as e:
            logging.warning(f"⏱️ Token validation timeout user={username}")
            raise NetworkError("Token validation timeout") from e
        except aiohttp.ClientError as e:
            logging.warning(
                f"💥 Network error during token validation: {type(e).__name__} user={username}"
            )
            raise NetworkError(f"Network error during validation: {e}") from e
        except Exception as e:  # noqa: BLE001
            import traceback

            logging.error(
                f"💥 Unexpected error during token validation: {type(e).__name__} user={username} error={str(e)} traceback={traceback.format_exc()}"
            )
            return False, None
