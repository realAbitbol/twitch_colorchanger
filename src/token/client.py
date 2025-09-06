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
from ..logs.logger import logger
from ..utils import format_duration


class TokenOutcome(str, Enum):
    VALID = "valid"
    REFRESHED = "refreshed"
    SKIPPED = "skipped"  # no action needed; still within safe threshold
    FAILED = "failed"


@dataclass
class TokenResult:
    outcome: TokenOutcome
    access_token: str | None
    refresh_token: str | None
    expiry: datetime | None


class TokenClient:
    def __init__(
        self, client_id: str, client_secret: str, http_session: aiohttp.ClientSession
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = http_session

    async def validate(self, username: str, access_token: str) -> TokenResult:
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
        if (
            not force_refresh
            and expiry
            and (expiry - datetime.now(UTC)).total_seconds()
            > TOKEN_REFRESH_THRESHOLD_SECONDS
        ):
            return TokenResult(
                TokenOutcome.SKIPPED, access_token, refresh_token, expiry
            )

        if not force_refresh:
            is_valid, remote_expiry = await self._validate_remote(
                username, access_token
            )
            if is_valid:
                final_expiry = remote_expiry or expiry
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
                logger.log_event(
                    "token", "valid_but_expiring", level=logging.WARNING, user=username
                )

        if not refresh_token:
            return TokenResult(TokenOutcome.FAILED, None, None, expiry)
        return await self.refresh(username, refresh_token)

    async def refresh(self, username: str, refresh_token: str) -> TokenResult:
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
                        safe_expires = max(
                            expires_in - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0
                        )
                        expiry = datetime.now(UTC) + timedelta(seconds=safe_expires)
                    human_expires = format_duration(expires_in)
                    logger.log_event(
                        "token",
                        "refresh_success",
                        user=username,
                        attempt=1,
                        expires_in=expires_in,
                        human=f"Token refreshed (lifetime {human_expires})",
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
            logger.log_event(
                "token",
                "refresh_invalid_response",
                level=logging.ERROR,
                missing_field="access_token",
                user=username,
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except OAuthError:
            logger.log_event(
                "token",
                "refresh_unauthorized",
                level=logging.ERROR,
                user=username,
                status=401,
                error_type="OAuthError",
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except RateLimitError:
            logger.log_event(
                "token",
                "refresh_rate_limited",
                level=logging.WARNING,
                user=username,
                status=429,
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except NetworkError as e:
            logger.log_event(
                "token",
                "refresh_network_error",
                level=logging.WARNING,
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "token",
                "refresh_error",
                level=logging.ERROR,
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)

    async def _validate_remote(
        self, username: str, access_token: str
    ) -> tuple[bool, datetime | None]:
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
                        # Apply the same safety buffer used on refresh so scheduling logic
                        # never attempts a refresh too late due to unbuffered validate path.
                        safe_expires = max(
                            expires_in - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0
                        )
                        expiry = datetime.now(UTC) + timedelta(seconds=safe_expires)
                        logger.log_event(
                            "token",
                            "validated",
                            level=logging.DEBUG,
                            user=username,
                            expires_in=expires_in,
                            buffered_expires_in=safe_expires,
                            human=f"Token valid (remaining {format_duration(expires_in)} raw, buffered {format_duration(safe_expires)})",
                        )
                    return True, expiry
                if resp.status == 401:
                    # 401 here usually just means the stored access token is expired; a refresh will follow.
                    # Demote to INFO to avoid alarming users on normal startup token rotations.
                    logger.log_event(
                        "token",
                        "validation_invalid",
                        level=logging.INFO,
                        user=username,
                        status=resp.status,
                    )
                elif resp.status == 429:
                    logger.log_event(
                        "token",
                        "validation_rate_limited",
                        level=logging.WARNING,
                        user=username,
                        status=resp.status,
                    )
                else:
                    logger.log_event(
                        "token",
                        "validation_failed_status",
                        level=logging.WARNING,
                        user=username,
                        status=resp.status,
                    )
                return False, None
        except TimeoutError as e:
            logger.log_event(
                "token", "validation_timeout", level=logging.WARNING, user=username
            )
            raise NetworkError("Token validation timeout") from e
        except aiohttp.ClientError as e:
            logger.log_event(
                "token",
                "validation_network_error",
                level=logging.WARNING,
                user=username,
                error_type=type(e).__name__,
            )
            raise NetworkError(f"Network error during validation: {e}") from e
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "token",
                "validation_error",
                level=logging.ERROR,
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None
