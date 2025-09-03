"""Unified token client consolidating validation and refresh logic.

Public API:
  * await TokenClient.validate(username, access_token, refresh_token, expiry)
      -> returns dict(status, access_token, refresh_token, expiry)
  * await TokenClient.ensure_fresh(...)
      -> like validate but triggers refresh if expiring within threshold
  * await TokenClient.refresh(..., force=False)
      -> force or conditional refresh

Statuses:
  valid, refreshed, failed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import aiohttp

from .constants import (
    TOKEN_REFRESH_SAFETY_BUFFER_SECONDS,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from .logger import logger


class TokenOutcome(str, Enum):
    VALID = "valid"
    REFRESHED = "refreshed"
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

    # --- Public API -----------------------------------------------------
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
        # If we have expiry and it's still above threshold and not forced, accept
        if (
            not force_refresh
            and expiry
            and (expiry - datetime.now()).total_seconds()
            > TOKEN_REFRESH_THRESHOLD_SECONDS
        ):
            return TokenResult(TokenOutcome.VALID, access_token, refresh_token, expiry)

        # Try remote validation first (may extend expiry)
        if not force_refresh:
            is_valid, remote_expiry = await self._validate_remote(
                username, access_token
            )
            if is_valid:
                final_expiry = remote_expiry or expiry
                if (
                    final_expiry
                    and (final_expiry - datetime.now()).total_seconds()
                    > TOKEN_REFRESH_THRESHOLD_SECONDS
                ):
                    return TokenResult(
                        TokenOutcome.VALID, access_token, refresh_token, final_expiry
                    )
                # Valid but expiring soon -> fall through to refresh
                logger.log_event(
                    "token", "valid_but_expiring", level=logging.WARNING, user=username
                )

        # Need refresh
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
                        logger.log_event(
                            "token",
                            "refresh_invalid_response",
                            level=logging.ERROR,
                            missing_field="access_token",
                            user=username,
                        )
                        return TokenResult(TokenOutcome.FAILED, None, None, None)
                    expiry = None
                    if expires_in:
                        safe_expires = max(
                            expires_in - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0
                        )
                        expiry = datetime.now() + timedelta(seconds=safe_expires)
                    logger.log_event(
                        "token",
                        "refresh_success",
                        user=username,
                        attempt=1,
                        expires_in=expires_in,
                    )
                    return TokenResult(
                        TokenOutcome.REFRESHED, new_access, new_refresh, expiry
                    )
                # Non-200
                await resp.text()  # consume for context (unused)
                logger.log_event(
                    "token",
                    "refresh_failed_status",
                    level=logging.ERROR,
                    status=resp.status,
                    user=username,
                )
                return TokenResult(TokenOutcome.FAILED, None, None, None)
        except TimeoutError:
            logger.log_event(
                "token",
                "refresh_timeout",
                level=logging.WARNING,
                user=username,
                attempt=1,
            )
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        except aiohttp.ClientError as e:  # type: ignore[name-defined]
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

    # --- Internal helpers -----------------------------------------------
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
                        expiry = datetime.now() + timedelta(seconds=expires_in)
                    return True, expiry
                if resp.status == 401:
                    logger.log_event(
                        "token",
                        "validation_invalid",
                        level=logging.WARNING,
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
        except TimeoutError:
            logger.log_event(
                "token", "validation_timeout", level=logging.WARNING, user=username
            )
            return False, None
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
