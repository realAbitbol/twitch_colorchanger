"""
Centralized token management for multiple Twitch users
Replaces per-bot TokenService instances with a singleton manager
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from secrets import SystemRandom

import aiohttp

from .constants import (
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from .token_client import TokenClient, TokenOutcome

try:
    from .structured_logger import get_logger  # type: ignore
except Exception:  # noqa: BLE001
    # Fallback to legacy logger if structured logger not available
    from .logger import logger as _legacy_logger  # type: ignore

    def get_logger():  # type: ignore
        return _legacy_logger


# Use SystemRandom for jitter to satisfy security lints
_jitter_rng = SystemRandom()

# Local timing constants (loop cadence / validation min interval)
# (interval constants imported from constants.py)


class TokenState(Enum):
    """Token lifecycle states"""

    FRESH = "fresh"  # > threshold remaining
    STALE = "stale"  # < threshold, needs refresh
    REFRESHING = "refreshing"  # Refresh in progress
    EXPIRED = "expired"  # Past expiry time


@dataclass
class TokenInfo:
    """Per-user token state"""

    username: str
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expiry: datetime | None = None
    state: TokenState = TokenState.FRESH

    # Refresh management
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_validation: float = 0


class TokenManager:
    """Centralized token management singleton"""

    _instance = None
    _initialized = False

    def __new__(cls, http_session: aiohttp.ClientSession):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, http_session: aiohttp.ClientSession):
        if TokenManager._initialized:
            return

        self.http_session = http_session
        self.tokens: dict[str, TokenInfo] = {}
        self.background_task: asyncio.Task | None = None
        self.running = False
        self.logger = get_logger()
        # TokenClient cache per (client_id, client_secret)
        self._client_cache: dict[tuple[str, str], TokenClient] = {}
        TokenManager._initialized = True

    async def start(self):
        """Start the background token refresh loop"""
        if self.running:
            return
        self.running = True
        self.background_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.log_event("token_manager", "start")
        await asyncio.sleep(0)  # Make function truly async

    async def stop(self):
        """Stop the token manager"""
        self.running = False
        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                # Clean up background task reference before re-raising
                self.background_task = None
                raise
            finally:
                self.background_task = None
        self.logger.log_event("token_manager", "stop", level=logging.WARNING)

    def register_user(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        expiry: datetime | None = None,
    ) -> None:
        """Register a user's tokens with the manager"""
        token_info = TokenInfo(
            username=username,
            access_token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            expiry=expiry,
        )

        # Determine initial state
        token_info.state = self._determine_token_state(token_info)

        self.tokens[username] = token_info
        self.logger.log_event(
            "token_manager",
            "user_registered",
            level=logging.DEBUG,
            username=username,
            state=token_info.state.value,
        )

    async def get_fresh_token(self, username: str) -> str | None:
        """Get a fresh token for the user, refreshing if needed"""
        if username not in self.tokens:
            self.logger.log_event(
                "token_manager",
                "not_registered",
                level=logging.ERROR,
                username=username,
            )
            return None

        token_info = self.tokens[username]

        # Quick check if token is fresh enough
        if self._is_token_fresh(token_info):
            return token_info.access_token

        # Validate or refresh via TokenClient
        success = await self._ensure_token_fresh(token_info)
        return token_info.access_token if success else None

    async def force_refresh(self, username: str) -> bool:
        if username not in self.tokens:
            return False
        token_info = self.tokens[username]
        async with token_info.refresh_lock:
            return await self._refresh_via_client(token_info, force=True)

    def get_token_info(self, username: str) -> TokenInfo | None:
        """Get token info for monitoring/debugging"""
        return self.tokens.get(username)

    async def _background_refresh_loop(self):
        """Background loop to proactively refresh tokens before they expire"""
        while self.running:
            try:
                # Check all tokens and refresh stale ones
                refresh_tasks = []

                for token_info in self.tokens.values():
                    if self._should_proactive_refresh(token_info):
                        # Schedule refresh (don't await to allow parallel refreshes)
                        task = asyncio.create_task(self._ensure_token_fresh(token_info))
                        refresh_tasks.append(task)

                # Wait for any refreshes to complete
                if refresh_tasks:
                    await asyncio.gather(*refresh_tasks, return_exceptions=True)

                # Sleep with jitter before next check
                base_sleep = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP
                jitter = _jitter_rng.uniform(0.8, 1.2)
                await asyncio.sleep(base_sleep * jitter)

            except asyncio.CancelledError:
                self.logger.log_event(
                    "token_manager", "loop_cancelled", level=logging.WARNING
                )
                raise
            except Exception as e:
                self.logger.log_event(
                    "token_manager",
                    "loop_error",
                    level=logging.ERROR,
                    error=str(e),
                )
                await asyncio.sleep(30)  # Error recovery delay

    def _determine_token_state(self, token_info: TokenInfo) -> TokenState:
        """Determine current state of a token"""
        if not token_info.expiry:
            return TokenState.FRESH  # No expiry info, assume fresh

        now = datetime.now()
        time_until_expiry = (token_info.expiry - now).total_seconds()

        if time_until_expiry <= 0:
            return TokenState.EXPIRED
        if time_until_expiry <= TOKEN_REFRESH_THRESHOLD_SECONDS:
            return TokenState.STALE
        return TokenState.FRESH

    def _is_token_fresh(self, token_info: TokenInfo) -> bool:
        """Quick check if token is fresh enough to use"""
        if token_info.state == TokenState.FRESH:
            # Double-check expiry hasn't changed
            current_state = self._determine_token_state(token_info)
            if current_state == TokenState.FRESH:
                return True
            else:
                token_info.state = current_state

        return False

    def _should_proactive_refresh(self, token_info: TokenInfo) -> bool:
        """Check if token should be proactively refreshed"""
        # Don't refresh if already in progress
        if token_info.state == TokenState.REFRESHING:
            return False

        # Refresh if stale or expired
        current_state = self._determine_token_state(token_info)
        return current_state in (TokenState.STALE, TokenState.EXPIRED)

    async def _ensure_token_fresh(self, token_info: TokenInfo) -> bool:
        async with token_info.refresh_lock:
            if self._is_token_fresh(token_info):
                return True
            return await self._refresh_via_client(token_info)

    def _get_client(self, token_info: TokenInfo) -> TokenClient:
        key = (token_info.client_id, token_info.client_secret)
        client = self._client_cache.get(key)
        if client is None:
            client = TokenClient(
                token_info.client_id, token_info.client_secret, self.http_session
            )
            self._client_cache[key] = client
        return client

    async def _refresh_via_client(
        self, token_info: TokenInfo, force: bool = False
    ) -> bool:
        # Skip rapid re-validation
        if (
            not force
            and time.time() - token_info.last_validation
            < TOKEN_MANAGER_VALIDATION_MIN_INTERVAL
        ):
            return False
        token_info.last_validation = time.time()
        client = self._get_client(token_info)
        try:
            token_info.state = TokenState.REFRESHING
            result = await client.ensure_fresh(
                token_info.username,
                token_info.access_token,
                token_info.refresh_token,
                token_info.expiry,
                force_refresh=force,
            )
            if result.outcome in (TokenOutcome.VALID, TokenOutcome.REFRESHED):
                if result.access_token:
                    token_info.access_token = result.access_token
                if result.refresh_token:
                    token_info.refresh_token = result.refresh_token
                token_info.expiry = result.expiry
                token_info.state = self._determine_token_state(token_info)
                if result.outcome == TokenOutcome.REFRESHED:
                    self.logger.log_event(
                        "token_manager", "refresh_success", username=token_info.username
                    )
                return True
            # Failed path -> mark stale or expired so loop can retry
            token_info.state = self._determine_token_state(token_info)
            if token_info.state == TokenState.FRESH:
                # If still reported fresh but outcome failed, degrade to STALE to force retry
                token_info.state = TokenState.STALE
            self.logger.log_event(
                "token_manager",
                "refresh_failed",
                level=20,
                username=token_info.username,
            )
            return False
        except Exception as e:  # noqa: BLE001
            token_info.state = self._determine_token_state(token_info)
            if token_info.state == TokenState.FRESH:
                token_info.state = TokenState.STALE
            self.logger.log_event(
                "token_manager",
                "refresh_failed",
                level=40,
                username=token_info.username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    # Removed direct _call_refresh_api; TokenClient handles network operations


# Global factory removed: TokenManager lifecycle handled by ApplicationContext
