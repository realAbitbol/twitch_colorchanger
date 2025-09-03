"""
Centralized token management for multiple Twitch users
Replaces per-bot TokenService instances with a singleton manager
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from secrets import SystemRandom

import aiohttp

try:
    from .structured_logger import get_logger  # type: ignore
except Exception:  # noqa: BLE001
    # Fallback to legacy logger if structured logger not available
    from .logger import logger as _legacy_logger  # type: ignore

    def get_logger():  # type: ignore
        return _legacy_logger


# Use SystemRandom for jitter to satisfy security lints
_jitter_rng = SystemRandom()

# Configuration constants
TOKEN_REFRESH_THRESHOLD = 3600  # 1 hour in seconds
TOKEN_SAFETY_BUFFER = 300  # 5 minutes buffer when refreshing
MAX_REFRESH_RETRIES = 3
BASE_RETRY_DELAY = 60  # Base delay between retries
MAX_RETRY_DELAY = 1800  # Max 30 minutes
VALIDATION_TIMEOUT = 30  # API call timeout


class TokenRefreshError(Exception):
    """Token refresh specific error"""

    pass


class TokenState(Enum):
    """Token lifecycle states"""

    FRESH = "fresh"  # > threshold remaining
    STALE = "stale"  # < threshold, needs refresh
    REFRESHING = "refreshing"  # Refresh in progress
    FAILED = "failed"  # Refresh failed, in cooldown
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
    refresh_attempts: int = 0
    last_refresh_attempt: float = 0
    last_validation: float = 0

    # Backoff tracking
    consecutive_failures: int = 0
    cooldown_until: float = 0


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

        # Global locks for coordination
        self._refresh_coordination_lock = asyncio.Lock()

        TokenManager._initialized = True

    async def start(self):
        """Start the background token refresh loop"""
        if self.running:
            return

        self.running = True
        self.background_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.info("Started centralized token manager")
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
        self.logger.warn("Stopped token manager")

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
        self.logger.debug(
            f"Registered with token manager (state: {token_info.state.value})",
            username=username,
        )

    async def get_fresh_token(self, username: str) -> str | None:
        """Get a fresh token for the user, refreshing if needed"""
        if username not in self.tokens:
            self.logger.error("Not registered with token manager", username=username)
            return None

        token_info = self.tokens[username]

        # Quick check if token is fresh
        if self._is_token_fresh(token_info):
            return token_info.access_token

        # Need to refresh or validate
        success = await self._ensure_token_fresh(token_info)
        return token_info.access_token if success else None

    async def force_refresh(self, username: str) -> bool:
        """Force immediate token refresh for a user"""
        if username not in self.tokens:
            return False

        token_info = self.tokens[username]
        async with token_info.refresh_lock:
            return await self._perform_refresh(token_info)

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
                base_sleep = 60  # Check every minute
                jitter = _jitter_rng.uniform(0.8, 1.2)
                await asyncio.sleep(base_sleep * jitter)

            except asyncio.CancelledError:
                self.logger.warn("Token refresh loop cancelled")
                raise
            except Exception as e:
                self.logger.error(f"Error in token refresh loop: {e}")
                await asyncio.sleep(30)  # Error recovery delay

    def _determine_token_state(self, token_info: TokenInfo) -> TokenState:
        """Determine current state of a token"""
        if not token_info.expiry:
            return TokenState.FRESH  # No expiry info, assume fresh

        now = datetime.now()
        time_until_expiry = (token_info.expiry - now).total_seconds()

        if time_until_expiry <= 0:
            return TokenState.EXPIRED
        elif time_until_expiry <= TOKEN_REFRESH_THRESHOLD:
            return TokenState.STALE
        else:
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
        # Don't refresh if already in progress or failed recently
        if token_info.state in (TokenState.REFRESHING, TokenState.FAILED):
            return False

        # Don't refresh if in cooldown
        if time.time() < token_info.cooldown_until:
            return False

        # Refresh if stale or expired
        current_state = self._determine_token_state(token_info)
        return current_state in (TokenState.STALE, TokenState.EXPIRED)

    async def _ensure_token_fresh(self, token_info: TokenInfo) -> bool:
        """Ensure token is fresh, refreshing if needed"""
        # Use lock to prevent duplicate refreshes for same user
        async with token_info.refresh_lock:
            # Re-check state under lock (another task might have refreshed)
            if self._is_token_fresh(token_info):
                return True

            # Try validation first (maybe token is still good)
            if await self._try_validation(token_info):
                return True

            # Need to refresh
            return await self._perform_refresh(token_info)

    async def _try_validation(self, token_info: TokenInfo) -> bool:
        """Try validating current token with Twitch API"""
        # Skip validation if we tried recently
        if time.time() - token_info.last_validation < 30:
            return False

        try:
            token_info.last_validation = time.time()

            headers = {"Authorization": f"OAuth {token_info.access_token}"}
            url = "https://id.twitch.tv/oauth2/validate"

            timeout = aiohttp.ClientTimeout(total=VALIDATION_TIMEOUT)
            async with self.http_session.get(
                url, headers=headers, timeout=timeout
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    expires_in = data.get("expires_in", 0)

                    # Update expiry from API response
                    if expires_in > 0:
                        token_info.expiry = datetime.now() + timedelta(
                            seconds=expires_in
                        )
                        token_info.state = self._determine_token_state(token_info)

                        # Only consider valid if above threshold
                        if token_info.state == TokenState.FRESH:
                            # Validated and still above freshness threshold
                            self.logger.debug(
                                f"Token validated, {expires_in}s remaining",
                                username=token_info.username,
                            )
                            return True

                # Token invalid or expires soon
                return False

        except Exception as e:
            self.logger.warn(
                f"Token validation error: {e}", username=token_info.username
            )
            return False

    async def _perform_refresh(self, token_info: TokenInfo) -> bool:
        """Perform actual token refresh"""
        if token_info.state == TokenState.REFRESHING:
            return False  # Already refreshing

        # Check if we should delay due to recent failures
        if time.time() < token_info.cooldown_until:
            self.logger.debug("Token refresh in cooldown", username=token_info.username)
            return False

        token_info.state = TokenState.REFRESHING
        token_info.refresh_attempts += 1
        token_info.last_refresh_attempt = time.time()

        try:
            self.logger.info(
                f"Refreshing token (attempt {token_info.refresh_attempts})",
                username=token_info.username,
            )

            # Refresh API call
            new_access, new_refresh, expires_in = await self._call_refresh_api(
                token_info
            )

            if new_access:
                # Success - update token info
                token_info.access_token = new_access
                if new_refresh:
                    token_info.refresh_token = new_refresh

                if expires_in:
                    # Apply safety buffer
                    safe_expires_in = max(expires_in - TOKEN_SAFETY_BUFFER, 0)
                    token_info.expiry = datetime.now() + timedelta(
                        seconds=safe_expires_in
                    )

                # Reset failure tracking
                token_info.state = TokenState.FRESH
                token_info.refresh_attempts = 0
                token_info.consecutive_failures = 0
                token_info.cooldown_until = 0

                self.logger.info(
                    "Token refreshed successfully", username=token_info.username
                )
                return True
            else:
                raise TokenRefreshError("Refresh API returned no token")

        except Exception as e:
            self.logger.error(
                f"Token refresh failed: {e}", username=token_info.username
            )

            # Handle failure
            token_info.consecutive_failures += 1
            token_info.state = TokenState.FAILED

            # Calculate cooldown with exponential backoff + jitter
            backoff_delay = min(
                BASE_RETRY_DELAY * (2**token_info.consecutive_failures), MAX_RETRY_DELAY
            )
            jitter = _jitter_rng.uniform(0.5, 1.5)
            cooldown = backoff_delay * jitter
            token_info.cooldown_until = time.time() + cooldown

            self.logger.warn(
                f"Refresh cooldown for {token_info.username}: {cooldown:.1f}s"
            )

            return False

    async def _call_refresh_api(
        self, token_info: TokenInfo
    ) -> tuple[str | None, str | None, int | None]:
        """Call Twitch refresh token API"""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": token_info.refresh_token,
            "client_id": token_info.client_id,
            "client_secret": token_info.client_secret,
        }

        url = "https://id.twitch.tv/oauth2/token"
        timeout = aiohttp.ClientTimeout(total=VALIDATION_TIMEOUT)

        async with self.http_session.post(url, data=data, timeout=timeout) as response:
            if response.status == 200:
                result = await response.json()
                return (
                    result.get("access_token"),
                    result.get("refresh_token"),
                    result.get("expires_in"),
                )
            else:
                error_text = await response.text()
                raise TokenRefreshError(f"HTTP {response.status}: {error_text}")


# Global instance management
_token_manager_instance: TokenManager | None = None


def get_token_manager(http_session: aiohttp.ClientSession) -> TokenManager:
    """Get or create the global token manager instance"""
    global _token_manager_instance
    if _token_manager_instance is None:
        _token_manager_instance = TokenManager(http_session)
    return _token_manager_instance


async def shutdown_token_manager():
    """Shutdown the global token manager"""
    global _token_manager_instance
    if _token_manager_instance:
        await _token_manager_instance.stop()
        _token_manager_instance = None
