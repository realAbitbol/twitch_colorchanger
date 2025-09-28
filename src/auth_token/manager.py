"""Token manager (moved from token_manager.py)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import aiohttp

from ..constants import (
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from .background_task_manager import BackgroundTaskManager
from .client import TokenOutcome
from .client_cache import ClientCache
from .hook_manager import HookManager
from .token_refresher import TokenRefresher
from .token_validator import TokenValidator
from .types import TokenState

T = TypeVar("T")


@dataclass
class TokenInfo:
    """Container for token information and metadata.

    Attributes:
        username: Associated username.
        access_token: Current access token.
        refresh_token: Refresh token for obtaining new access tokens.
        client_id: Twitch client ID.
        client_secret: Twitch client secret.
        expiry: Token expiry datetime.
        state: Current token state.
        refresh_lock: Lock for thread-safe refresh operations.
        last_validation: Timestamp of last validation.
        forced_unknown_attempts: Count of forced refreshes for unknown expiry.
        original_lifetime: Baseline lifetime in seconds when first known.
    """

    username: str
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expiry: datetime | None = None
    state: TokenState = TokenState.FRESH
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_validation: float = 0
    forced_unknown_attempts: int = 0  # count of forced refreshes due to unknown expiry
    original_lifetime: int | None = (
        None  # seconds (baseline when token/expiry first known or refreshed)
    )


class TokenManager:
    """Singleton manager for handling Twitch OAuth tokens.

    Manages token validation, refresh, and background monitoring for multiple users.
    Uses a singleton pattern to ensure single instance per event loop.
    """

    _instance = None  # Simple singleton; not thread-safe by design (single event loop).

    def __new__(cls, http_session: aiohttp.ClientSession) -> TokenManager:
        """Create or return the singleton instance.

        Args:
            http_session: HTTP session for API requests.

        Returns:
            The singleton TokenManager instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, http_session: aiohttp.ClientSession):
        """Initialize the token manager singleton instance.

        Args:
            http_session: HTTP session for making API requests.
        """
        if http_session is None:
            raise TypeError("http_session cannot be None")
        # Guard: if already initialized (singleton), skip re-initialization.
        if getattr(self, "_inst_initialized", False):  # pragma: no cover - simple guard
            return
        # Core state
        self.http_session = http_session
        self.tokens: dict[str, TokenInfo] = {}
        self._tokens_lock = asyncio.Lock()
        self.running = False
        # Paused users for background refresh
        self._paused_users: set[str] = set()
        # Registered backends for immediate token propagation
        self._backends: dict[str, Any] = {}
        # Composed components
        self.validator = TokenValidator(self)
        self.refresher = TokenRefresher(self)
        self.background_task_manager = BackgroundTaskManager(self)
        self.hook_manager = HookManager(self)
        self.client_cache = ClientCache(self)
        # Mark as initialized to avoid repeating work on future constructions.
        self._inst_initialized = True

    async def start(self) -> None:
        """Start the token manager and background refresh loop.

        Performs initial validation and launches the background task for
        periodic token management.

        Raises:
            aiohttp.ClientError: If network requests fail during validation.
            ValueError: If token data is invalid.
            RuntimeError: If background task creation fails.
        """
        if self.running:
            return
        self.running = True
        # Initial validation pass before launching background loop
        await self._initial_validation_pass()
        await self.background_task_manager.start()
        logging.debug("▶️ Started centralized token manager")
        await asyncio.sleep(0)

    async def _initial_validation_pass(self) -> None:
        """Validate all known tokens once at startup.

        Strategy:
        - If expiry unknown: record skipped (handled later by unknown-expiry logic).
        - Else validate remotely; if remaining < proactive threshold (1h) refresh.
        - If validation fails: force refresh.
        """
        if not self.tokens:
            return
        async with self._tokens_lock:
            for username, info in self.tokens.items():
                await self._initial_validate_user(username, info)

    async def _initial_validate_user(self, username: str, info: TokenInfo) -> None:
        """Validate a user's token during initial startup validation.

        Performs remote validation if expiry is known, or skips if unknown.
        Refreshes proactively if remaining time is below threshold.

        Args:
            username: Username associated with the token.
            info: TokenInfo object containing token details.

        Returns:
            None

        Raises:
            aiohttp.ClientError: If network request fails.
            ValueError: If token data is invalid.
            RuntimeError: If validation process encounters an error.
        """
        try:
            if info.expiry is None:
                logging.info(
                    f"❔ Startup validation skipped (unknown expiry) user={username}"
                )
                return
            outcome = await self.validate(username)
            remaining = self.validator.remaining_seconds(info)
            if outcome == TokenOutcome.VALID and remaining is not None:
                if remaining < TOKEN_REFRESH_THRESHOLD_SECONDS:
                    ref = await self.ensure_fresh(username)
                    # Inline the conditional action so the audit tool (AST walker)
                    # can statically discover both template literals; previously this
                    # used a variable which made the two variants appear "unused".
                    if ref == TokenOutcome.REFRESHED:
                        logging.info(
                            f"✅ Startup validated & refreshed token user={username} remaining={int(remaining)}s outcome={ref.value}"
                        )
                    else:
                        logging.info(
                            f"⏳ Startup validated token within threshold (no refresh) user={username} remaining={int(remaining)}s outcome={ref.value}"
                        )
                else:
                    logging.info(
                        f"✅ Startup validated token user={username} remaining={int(remaining)}s"
                    )
            else:
                ref = await self.ensure_fresh(username, force_refresh=True)
                logging.info(
                    f"🔄 Startup validation failed forcing refresh outcome={ref.value} user={username}"
                )
        except (aiohttp.ClientError, ValueError, RuntimeError) as e:
            logging.debug(
                f"⚠️ Startup validation error user={username} type={type(e).__name__} error={str(e)}"
            )

    async def stop(self) -> None:
        """Stop the token manager and background refresh loop.

        Cancels the background task and cleans up resources.
        """
        if not self.running:
            return
        self.running = False
        await self.background_task_manager.stop()

    def get_background_task_health(self) -> Any:
        """Get health status of background tasks for monitoring.

        Returns:
            TaskHealthStatus object with health metrics.
        """
        return self.background_task_manager.get_health_status()

    async def pause_background_refresh(self, username: str) -> None:
        """Pause background refresh for a specific user.

        Args:
            username: Username to pause background refresh for.
        """
        async with self._tokens_lock:
            if username in self.tokens:
                self._paused_users.add(username)
                logging.debug(f"⏸️ Paused background refresh for user={username}")

    async def resume_background_refresh(self, username: str) -> None:
        """Resume background refresh for a specific user.

        Args:
            username: Username to resume background refresh for.
        """
        async with self._tokens_lock:
            self._paused_users.discard(username)
            logging.debug(f"▶️ Resumed background refresh for user={username}")

    async def register_update_hook(
        self, username: str, hook: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a coroutine hook invoked after a successful token refresh.

        Hooks are additive (multiple hooks can be registered per user).
        Each hook is scheduled fire-and-forget after a token change.
        """
        await self.hook_manager.register_update_hook(username, hook)

    async def register_invalidation_hook(
        self, username: str, hook: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a coroutine hook invoked when tokens are invalidated.

        Hooks are additive (multiple hooks can be registered per user).
        Each hook is scheduled fire-and-forget when tokens are invalidated.
        """
        await self.hook_manager.register_invalidation_hook(username, hook)

    async def register_eventsub_backend(self, username: str, backend: Any) -> None:
        """Register chat backend for immediate token propagation.

        - If backend has update_access_token(new_token), prefer that.
        - Else if backend has update_token(new_token), use that.
        Silently do nothing if neither is available.
        """
        propagate_attr = None
        if hasattr(backend, "update_access_token"):
            propagate_attr = "update_access_token"
        elif hasattr(backend, "update_token"):
            propagate_attr = "update_token"
        if not propagate_attr:
            return

        # Store backend for immediate propagation during token refresh
        async with self._tokens_lock:
            self._backends[username] = (backend, propagate_attr)

    def _propagate_token_immediately(self, username: str, access_token: str) -> None:
        """Propagate token to registered backends immediately.

        Called synchronously during token refresh to minimize propagation delays.
        """
        backend_info = self._backends.get(username)
        if not backend_info:
            return
        backend, propagate_attr = backend_info
        try:
            getattr(backend, propagate_attr)(access_token)
        except (ValueError, RuntimeError, TypeError) as e:
            logging.warning(
                f"⚠️ EventSub token propagation error user={username}: {str(e)}"
            )

    async def _upsert_token_info(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        expiry: datetime | None,
    ) -> TokenInfo:
        """Internal helper to insert/update token state (called by TwitchColorBot)."""
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info is None:
                info = TokenInfo(
                    username=username,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    client_id=client_id,
                    client_secret=client_secret,
                    expiry=expiry,
                )
                self.tokens[username] = info
                if expiry:
                    remaining = int((expiry - datetime.now(UTC)).total_seconds())
                    if remaining > 0:
                        info.original_lifetime = remaining
            else:
                info.access_token = access_token
                info.refresh_token = refresh_token
                info.client_id = client_id
                info.client_secret = client_secret
                info.expiry = expiry
                info.state = TokenState.FRESH
                if expiry and info.original_lifetime is None:
                    remaining = int((expiry - datetime.now(UTC)).total_seconds())
                    if remaining > 0:
                        info.original_lifetime = remaining
            return info

    async def remove(self, username: str) -> bool:
        """Remove a user from token tracking (e.g., config removal)."""
        async with self._tokens_lock:
            if username in self.tokens:
                del self.tokens[username]
                logging.debug(f"🗑️ Removed token entry user={username}")
                return True
        return False

    async def prune(self, active_usernames: set[str]) -> int:
        """Prune tokens not in active set; return count removed."""
        async with self._tokens_lock:
            to_remove = [u for u in self.tokens if u not in active_usernames]
            for u in to_remove:
                del self.tokens[u]
            if to_remove:
                logging.info(
                    f"🧹 Pruned tokens removed={len(to_remove)} remaining={len(self.tokens)}"
                )
            return len(to_remove)

    async def get_info(self, username: str) -> TokenInfo | None:
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info:
                async with info.refresh_lock:
                    return info
            return None


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
        return await self.refresher.ensure_fresh(username, force_refresh)
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
        return await self.validator.validate(username)

