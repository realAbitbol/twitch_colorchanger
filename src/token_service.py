"""
Token service for unified token validation and refresh logic
"""

import asyncio
import random
from datetime import datetime, timedelta
from enum import Enum

import aiohttp

from .logger import logger


class TokenStatus(Enum):
    """Status of token validation result"""

    VALID = "valid"
    REFRESHED = "refreshed"
    FAILED = "failed"


class TokenService:
    """Service for managing token validation and refresh"""

    def __init__(
        self, client_id: str, client_secret: str, http_session: aiohttp.ClientSession
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http_session = http_session
        self._refresh_retry_count: dict[
            str, int
        ] = {}  # Track retry attempts per username
        self._last_refresh_attempt: dict[
            str, float
        ] = {}  # Track last refresh attempt time

    async def validate_and_refresh(
        self,
        access_token: str,
        refresh_token: str,
        username: str,
        token_expiry: datetime | None = None,
        force_refresh: bool = False,
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None]:
        """
        Validate and refresh token if needed with retry logic

        Returns:
            (status, new_access_token, new_refresh_token, new_expiry)
        """
        # Try cached validation first
        if not force_refresh:
            result = self._try_cached_validation(
                access_token, refresh_token, username, token_expiry
            )
            if result:
                return result

        # Try live token validation
        if not force_refresh:
            result = await self._try_live_validation(
                access_token, refresh_token, username, token_expiry
            )
            if result:
                return result

        # Perform token refresh with retries
        return await self._perform_token_refresh(refresh_token, username)

    def _try_cached_validation(
        self,
        access_token: str,
        refresh_token: str,
        username: str,
        token_expiry: datetime | None,
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None] | None:
        """Try validation using cached expiry information"""
        if self._is_token_still_valid(token_expiry):
            # Reset retry count on successful validation
            self._refresh_retry_count.pop(username, None)
            return TokenStatus.VALID, access_token, refresh_token, token_expiry
        return None

    async def _try_live_validation(
        self,
        access_token: str,
        refresh_token: str,
        username: str,
        token_expiry: datetime | None,
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None] | None:
        """Try validation using live API call"""
        is_valid, actual_expiry = await self._validate_token(access_token, username)
        if is_valid:
            # Token is valid, use actual expiry from validation or keep original
            final_expiry = actual_expiry if actual_expiry else token_expiry

            # Check if the token has enough time remaining (same logic as cached validation)
            if self._is_token_still_valid(final_expiry):
                # Reset retry count on successful validation
                self._refresh_retry_count.pop(username, None)
                return TokenStatus.VALID, access_token, refresh_token, final_expiry
            else:
                # Token is valid but expires soon, should be refreshed
                logger.warning(
                    "token_valid_but_expiring",
                    user=username,
                    action="refresh",
                )
                return None
        return None

    async def _perform_token_refresh(
        self, refresh_token: str, username: str
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None]:
        """Perform token refresh with retry logic"""
        # Check if we're rate limited for this user
        if self._should_delay_refresh(username):
            logger.warning(
                "token_refresh_delayed",
                user=username,
                reason="recent_failures",
                retry_count=self._refresh_retry_count.get(username, 0),
            )
            return TokenStatus.FAILED, None, None, None
        logger.info("token_refresh_needed", user=username)

        # Try refresh with retries
        for attempt in range(3):  # Max 3 attempts
            result = await self._try_single_refresh(refresh_token, username, attempt)
            if result:
                return result

            # Wait before retry (except after last attempt)
            if attempt < 2:
                delay = (2**attempt) + random.uniform(0, 1)  # nosec B311 - non-cryptographic jitter for retry delays
                logger.warning(
                    "token_refresh_retry_scheduled",
                    user=username,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)

        # All attempts failed
        return self._handle_refresh_failure(username)

    async def _try_single_refresh(
        self, refresh_token: str, username: str, attempt: int
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None] | None:
        """Try a single refresh attempt"""
        try:
            (
                new_access_token,
                new_refresh_token,
                expires_in,
            ) = await self._refresh_token_with_retry(refresh_token, username, attempt)

            if new_access_token:
                # Calculate expiry time with buffer
                new_expiry = (
                    datetime.now() + timedelta(seconds=expires_in - 300)
                    if expires_in
                    else None
                )
                logger.info(
                    "token_refresh_success",
                    user=username,
                    attempt=attempt + 1,
                    expires_in=expires_in,
                )
                # Reset retry tracking on success
                self._refresh_retry_count.pop(username, None)
                self._last_refresh_attempt.pop(username, None)
                return (
                    TokenStatus.REFRESHED,
                    new_access_token,
                    new_refresh_token,
                    new_expiry,
                )

        except Exception as e:
            logger.error(
                "token_refresh_attempt_error",
                user=username,
                attempt=attempt + 1,
                error=str(e),
                error_type=type(e).__name__,
            )

        return None

    def _handle_refresh_failure(
        self, username: str
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None]:
        """Handle failure after all refresh attempts"""
        self._refresh_retry_count[username] = (
            self._refresh_retry_count.get(username, 0) + 1
        )
        self._last_refresh_attempt[username] = datetime.now().timestamp()
        logger.error(
            "token_refresh_failed",
            user=username,
            attempts=3,
            retry_count=self._refresh_retry_count[username],
        )
        return TokenStatus.FAILED, None, None, None

    def _should_delay_refresh(self, username: str) -> bool:
        """Check if we should delay refresh due to recent failures"""
        retry_count = self._refresh_retry_count.get(username, 0)
        last_attempt = self._last_refresh_attempt.get(username)

        if retry_count < 3:
            return False

        if last_attempt:
            # Progressive backoff: wait longer after more failures
            min_delay = min(300 * (2 ** (retry_count - 3)), 3600)  # Max 1 hour
            time_since_last = datetime.now().timestamp() - last_attempt
            return time_since_last < min_delay

        return False

    async def _refresh_token_with_retry(
        self, refresh_token: str, username: str, attempt: int
    ) -> tuple[str | None, str | None, int | None]:
        """Refresh token with improved error handling"""
        try:
            return await self._refresh_token(refresh_token, username)
        except TimeoutError:
            logger.warning(
                "token_refresh_timeout",
                user=username,
                attempt=attempt + 1,
            )
            return None, None, None
        except aiohttp.ClientError as e:
            logger.warning(
                "token_refresh_network_error",
                user=username,
                attempt=attempt + 1,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None, None, None

    def _is_token_still_valid(self, token_expiry: datetime | None) -> bool:
        """Check if token is still valid and has more than 1 hour remaining"""
        if not token_expiry:
            return False

        now = datetime.now()
        time_until_expiry = (token_expiry - now).total_seconds()

        # Token should be refreshed if it expires in less than 1 hour (3600 seconds)
        return time_until_expiry > 3600

    async def _validate_token(
        self, access_token: str, username: str
    ) -> tuple[bool, datetime | None]:
        """Validate the token with Twitch API and get expiry information with timeout"""
        try:
            headers = {
                "Authorization": f"OAuth {access_token}",
            }

            url = "https://id.twitch.tv/oauth2/validate"

            # Add timeout to prevent hanging
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.http_session.get(
                url, headers=headers, timeout=timeout
            ) as response:
                if response.status == 200:
                    response_data = await response.json()
                    expires_in = response_data.get("expires_in")

                    # Calculate expiry time from expires_in seconds
                    expiry_time = None
                    if expires_in:
                        expiry_time = datetime.now() + timedelta(seconds=expires_in)

                    return True, expiry_time

                # Log specific error codes
                if response.status == 401:
                    logger.warning(
                        "token_validation_invalid",
                        user=username,
                        status=response.status,
                    )
                elif response.status == 429:
                    logger.warning(
                        "token_validation_rate_limited",
                        user=username,
                        status=response.status,
                    )
                else:
                    logger.warning(
                        "token_validation_failed_status",
                        user=username,
                        status=response.status,
                    )
                return False, None

        except TimeoutError:
            logger.warning("token_validation_timeout", user=username)
            return False, None
        except aiohttp.ClientError as e:
            logger.warning(
                "token_validation_network_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None
        except Exception as e:
            logger.error(
                "token_validation_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None

    async def _refresh_token(
        self, refresh_token: str, username: str
    ) -> tuple[str | None, str | None, int | None]:
        """Refresh the access token using refresh token with improved error handling"""
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

            url = "https://id.twitch.tv/oauth2/token"

            # Add timeout to prevent hanging
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.http_session.post(
                url, data=data, timeout=timeout
            ) as response:
                if response.status == 200:
                    response_data = await response.json()
                    new_access_token = response_data.get("access_token")
                    new_refresh_token = response_data.get(
                        "refresh_token", refresh_token
                    )
                    expires_in = response_data.get("expires_in")

                    # Validate that we got required fields
                    if not new_access_token:
                        logger.error(
                            "token_refresh_invalid_response",
                            user=username,
                            missing_field="access_token",
                        )
                        return None, None, None

                    return new_access_token, new_refresh_token, expires_in

                # Parse error response for better debugging
                try:
                    error_data = await response.json()
                    error_msg = error_data.get("message", "Unknown error")
                    error_type = error_data.get("error", "unknown")
                except (aiohttp.ContentTypeError, ValueError, KeyError):
                    error_msg = await response.text()
                    error_type = "parse_error"

                if response.status == 400:
                    logger.error(
                        "token_refresh_invalid_token",
                        user=username,
                        status=response.status,
                        error_type=error_type,
                        error_message=error_msg,
                    )
                elif response.status == 401:
                    logger.error(
                        "token_refresh_unauthorized",
                        user=username,
                        status=response.status,
                        error_type=error_type,
                        error_message=error_msg,
                    )
                elif response.status == 429:
                    logger.warning(
                        "token_refresh_rate_limited",
                        user=username,
                        status=response.status,
                    )
                else:
                    logger.error(
                        "token_refresh_http_error",
                        user=username,
                        status=response.status,
                        error_type=error_type,
                        error_message=error_msg,
                    )
                return None, None, None

        except TimeoutError:
            logger.error("token_refresh_timeout", user=username)
            return None, None, None
        except aiohttp.ClientError as e:
            logger.error(
                "token_refresh_network_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None, None, None
        except Exception as e:
            logger.error(
                "token_refresh_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None, None, None

    def next_check_delay(self, token_expiry: datetime | None) -> float:
        """Calculate the next token check delay in seconds with smart timing"""
        if not token_expiry:
            return 300  # Default 5 minutes if no expiry info

        now = datetime.now()
        time_until_expiry = (token_expiry - now).total_seconds()

        # Debug logging to understand scheduling decisions
        logger.debug(
            "token_schedule_debug",
            seconds_remaining=time_until_expiry,
        )

        # If token is already expired or expires very soon, check immediately
        if time_until_expiry <= 60:  # Less than 1 minute
            return 10  # Check in 10 seconds

        # Smart adaptive timing based on remaining time:
        if time_until_expiry <= 300:  # Less than 5 minutes
            # Check every minute when close to expiry
            return 60
        elif time_until_expiry <= 900:  # Less than 15 minutes
            # Check every 2 minutes when moderately close
            return 120
        elif time_until_expiry <= 1800:  # Less than 30 minutes
            # Check every 5 minutes
            return 300
        elif time_until_expiry <= 3600:  # Less than or equal to 1 hour
            # This should ideally not happen - token should have been refreshed
            # But check very frequently as a safety measure
            return 300  # Check every 5 minutes instead of 10
        else:
            # For tokens with >1 hour remaining, check 55 minutes before expiry
            # This ensures we catch tokens before they hit the 1-hour refresh threshold
            check_time = token_expiry - timedelta(minutes=55)
            delay = (check_time - now).total_seconds()

            # Ensure reasonable bounds: min 10 minutes, max 30 minutes
            return max(600, min(delay, 1800))
