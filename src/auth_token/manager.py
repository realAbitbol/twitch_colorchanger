"""Token manager (moved from token_manager.py)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from secrets import SystemRandom
from typing import Any, TypeVar

import aiohttp

from ..api.twitch import TwitchAPI
from ..constants import (
    EVENTSUB_CONSECUTIVE_401_THRESHOLD,
    REQUIRED_SCOPES,
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_CONCURRENT_LIMIT,
    TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL,
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from ..errors.eventsub import AuthenticationError
from ..utils import format_duration
from .client import RefreshErrorType, TokenClient, TokenOutcome, TokenResult

T = TypeVar("T")

_jitter_rng = SystemRandom()


class TokenState(Enum):
    """Enumeration of token freshness states.

    Attributes:
        FRESH: Token is recently obtained or refreshed.
        STALE: Token is valid but nearing expiry.
        EXPIRED: Token has expired and needs refresh.
    """

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


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
        recorded_scopes: Set of validated OAuth scopes.
        consecutive_401_count: Count of consecutive 401 errors.
        invalid_callback: Optional callback for token invalidation events.
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
    recorded_scopes: set[str] = field(default_factory=set)
    consecutive_401_count: int = 0
    invalid_callback: Callable[[], Coroutine[Any, Any, None]] | None = None


class TokenManager:
    """Singleton manager for handling Twitch OAuth tokens.

    Manages token validation, refresh, and background monitoring for multiple users.
    Uses a singleton pattern to ensure single instance per event loop.
    """

    _instance = None  # Simple singleton; not thread-safe by design (single event loop).
    background_task: asyncio.Task[Any] | None

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
        self.api = TwitchAPI(http_session)
        self.tokens: dict[str, TokenInfo] = {}
        self._tokens_lock = asyncio.Lock()
        self._client_cache_lock = asyncio.Lock()
        self._token_update_lock = asyncio.Lock()
        self._hooks_lock = asyncio.Lock()
        self.background_task: asyncio.Task[Any] | None = None
        self.running = False
        self._client_cache: dict[tuple[str, str], TokenClient] = {}
        # Registered per-user async hooks (called after successful token refresh).
        # Multiple hooks can be registered (e.g., persist + propagate to backends).
        self._update_hooks: dict[
            str, list[Callable[[], Coroutine[Any, Any, None]]]
        ] = {}
        # Registered per-user async invalidation hooks (called when tokens are invalidated).
        self._invalidation_hooks: dict[
            str, list[Callable[[], Coroutine[Any, Any, None]]]
        ] = {}
        # Retained background tasks (e.g. persistence hooks) to prevent premature GC.
        self._hook_tasks: list[asyncio.Task[Any]] = []
        # Semaphore for rate limiting concurrent background processing
        self._concurrent_semaphore = asyncio.Semaphore(TOKEN_MANAGER_CONCURRENT_LIMIT)
        # Paused users for background refresh
        self._paused_users: set[str] = set()
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
        # Defensive: if a previous background task is still lingering (e.g. rapid
        # stop/start where stop hasn't fully awaited cancellation yet), ensure it
        # is cancelled and awaited to avoid multiple loops.
        if self.background_task and not self.background_task.done():
            logging.debug("Cancelling stale background task before restart")
            try:
                self.background_task.cancel()
                await self.background_task
            except asyncio.CancelledError:
                raise
            except (ValueError, TypeError, RuntimeError) as e:
                logging.debug(f"⚠️ Error cancelling stale background task: {str(e)}")
            finally:
                self.background_task = None
        self.running = True
        # Initial validation pass before launching background loop
        await self._initial_validation_pass()
        self.background_task = asyncio.create_task(self._background_refresh_loop())
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
            remaining = self._remaining_seconds(info)
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
        if self.background_task:
            try:
                self.background_task.cancel()
                await self.background_task
            except (RuntimeError, OSError, ValueError) as e:
                logging.error(f"Error awaiting cancelled background task: {e}")
            finally:
                self.background_task = None

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
        async with self._hooks_lock:
            lst = self._update_hooks.get(username)
            if lst is None:
                self._update_hooks[username] = [hook]
            else:
                lst.append(hook)

    async def register_invalidation_hook(
        self, username: str, hook: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a coroutine hook invoked when tokens are invalidated.

        Hooks are additive (multiple hooks can be registered per user).
        Each hook is scheduled fire-and-forget when tokens are invalidated.
        """
        async with self._hooks_lock:
            lst = self._invalidation_hooks.get(username)
            if lst is None:
                self._invalidation_hooks[username] = [hook]
            else:
                lst.append(hook)

    async def register_eventsub_backend(self, username: str, backend: Any) -> None:
        """Register chat backend for automatic token propagation.

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

        async def _propagate() -> None:  # coroutine required by register_update_hook
            async with self._tokens_lock:
                info = self.tokens.get(username)
                if not info or not info.access_token:
                    return
                try:
                    getattr(backend, propagate_attr)(info.access_token)
                except (ValueError, RuntimeError, TypeError) as e:
                    logging.warning(
                        f"⚠️ EventSub token propagation error user={username}: {str(e)}"
                    )
                # tiny await to satisfy linters that expect async use
                await asyncio.sleep(0)

        await self.register_update_hook(username, _propagate)

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

    async def set_invalid_callback(
        self, username: str, callback: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for token invalidation events.

        The callback will be invoked when the token is detected as invalid
        (e.g., after consecutive 401 errors).

        Args:
            username: Username associated with the token.
            callback: Async callable to invoke on token invalidation.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info:
                info.invalid_callback = callback

    async def handle_401_error(self, username: str) -> None:
        """Handle a 401 Unauthorized error with threshold-based invalidation.

        Increments the consecutive 401 counter and triggers invalidation
        if the threshold is exceeded.

        Args:
            username: Username associated with the token.

        Raises:
            AuthenticationError: If token is invalidated due to threshold.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if not info:
                return
            info.consecutive_401_count += 1
        logging.warning(
            f"🚫 EventSub 401 error for user {username}, count={info.consecutive_401_count}"
        )

        if info.consecutive_401_count >= EVENTSUB_CONSECUTIVE_401_THRESHOLD:
            logging.error(
                f"🚫 Token invalidated for user {username} due to {info.consecutive_401_count} consecutive 401 errors"
            )
            # Reset counter
            info.consecutive_401_count = 0
            # Trigger invalidation callback
            if info.invalid_callback:
                try:
                    await info.invalid_callback()
                except Exception as e:
                    logging.warning(
                        f"⚠️ Error in token invalid callback for user {username}: {str(e)}"
                    )
            # Raise authentication error
            raise AuthenticationError(
                f"Token invalidated after {EVENTSUB_CONSECUTIVE_401_THRESHOLD} consecutive 401 errors",
                user_id=username,
                operation_type="handle_401",
            )

    async def handle_401_and_refresh(self, username: str) -> str | None:
        """Handle 401 error by refreshing token and returning new token.

        Args:
            username: Username associated with the token.

        Returns:
            The new access token if refresh successful, None otherwise.
        """
        try:
            refreshed = await self.refresh_token(username)
            if refreshed:
                info = await self.get_info(username)
                if info and info.access_token:
                    await self.reset_401_counter(username)
                    return info.access_token
            return None
        except Exception as e:
            logging.error(f"401 refresh failed for user {username}: {e}")
            return None

    async def get_scopes(self, username: str) -> set[str]:
        """Get the currently recorded OAuth scopes.

        Args:
            username: Username associated with the token.

        Returns:
            Set of recorded scopes.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
        return info.recorded_scopes.copy() if info else set()

    async def check_scopes(
        self, username: str, required_scopes: set[str] | frozenset[str]
    ) -> bool:
        """Check if token has required scopes.

        Args:
            username: Username associated with the token.
            required_scopes: Set of scopes that are required.

        Returns:
            True if token has all required scopes, False otherwise.
        """
        current_scopes = await self.get_scopes(username)
        return required_scopes.issubset(current_scopes)

    # Backward compatibility methods
    async def validate_token(
        self, username_or_token: str, access_token: str = ""
    ) -> bool:
        if access_token == "":
            # Backward compatibility: username_or_token is access_token
            access_token = username_or_token
            # For backward compatibility, try to find a user with this token
            async with self._tokens_lock:
                for username, info in self.tokens.items():
                    if info.access_token == access_token:
                        return await self._validate_token_impl(username, access_token)
            return False
        else:
            # Normal case: username_or_token is username
            username = username_or_token
            return await self._validate_token_impl(username, access_token)

    async def handle_401_error_legacy(self, username: str | None = None) -> None:
        """Handle 401 error (backward compatibility method).

        Args:
            username: Username associated with the token (optional for backward compatibility).
        """
        if username is None:
            # For backward compatibility, try to find a user with 401 errors
            async with self._tokens_lock:
                for user, info in self.tokens.items():
                    if info.consecutive_401_count > 0:
                        username = user
                        break
        if username:
            await self._handle_401_error(username)

    async def get_scopes_legacy(self, username: str | None = None) -> set[str]:
        """Get scopes (backward compatibility method).

        Args:
            username: Username associated with the token (optional for backward compatibility).

        Returns:
            Set of recorded scopes.
        """
        if username is None:
            # For backward compatibility, return scopes from first user
            async with self._tokens_lock:
                for info in self.tokens.values():
                    return info.recorded_scopes.copy()
        if username:
            return await self._get_scopes(username)
        return set()

    async def reset_401_counter_legacy(self, username: str | None = None) -> None:
        """Reset 401 counter (backward compatibility method).

        Args:
            username: Username associated with the token (optional for backward compatibility).
        """
        if username is None:
            # For backward compatibility, reset all counters
            async with self._tokens_lock:
                for info in self.tokens.values():
                    if info.consecutive_401_count > 0:
                        info.consecutive_401_count = 0
        elif username:
            await self._reset_401_counter(username)

    async def ensure_valid_token_legacy(
        self, username: str | None = None
    ) -> str | None:
        """Ensure token is valid (backward compatibility method).

        Args:
            username: Username associated with the token (optional for backward compatibility).

        Returns:
            Valid access token or None.
        """
        if username is None:
            # For backward compatibility, try first user
            async with self._tokens_lock:
                for user in self.tokens:
                    username = user
                    break
        if username:
            return await self._ensure_valid_token(username)
        return None

    async def set_invalid_callback_legacy(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
        username: str | None = None,
    ) -> None:
        """Set invalid callback (backward compatibility method).

        Args:
            callback: Callback function.
            username: Username associated with the token (optional for backward compatibility).
        """
        if username is None:
            # For backward compatibility, set for first user
            async with self._tokens_lock:
                for user in self.tokens:
                    username = user
                    break
        if username:
            await self._set_invalid_callback(username, callback)

    # Private methods renamed to avoid conflicts
    async def _get_scopes(self, username: str) -> set[str]:
        """Get the currently recorded OAuth scopes.

        Args:
            username: Username associated with the token.

        Returns:
            Set of recorded scopes.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
        return info.recorded_scopes.copy() if info else set()

    async def _handle_401_error(self, username: str) -> None:
        """Handle a 401 Unauthorized error with threshold-based invalidation.

        Args:
            username: Username associated with the token.

        Raises:
            AuthenticationError: If token is invalidated due to threshold.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if not info:
                return
            info.consecutive_401_count += 1
        logging.warning(
            f"🚫 EventSub 401 error for user {username}, count={info.consecutive_401_count}"
        )

        if info.consecutive_401_count >= EVENTSUB_CONSECUTIVE_401_THRESHOLD:
            logging.error(
                f"🚫 Token invalidated for user {username} due to {info.consecutive_401_count} consecutive 401 errors"
            )
            # Reset counter
            info.consecutive_401_count = 0
            # Trigger invalidation callback
            if info.invalid_callback:
                try:
                    await info.invalid_callback()
                except Exception as e:
                    logging.warning(
                        f"⚠️ Error in token invalid callback for user {username}: {str(e)}"
                    )
            # Raise authentication error
            raise AuthenticationError(
                f"Token invalidated after {EVENTSUB_CONSECUTIVE_401_THRESHOLD} consecutive 401 errors",
                user_id=username,
                operation_type="handle_401",
            )

    async def _reset_401_counter(self, username: str) -> None:
        """Reset the consecutive 401 error counter.

        Args:
            username: Username associated with the token.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info and info.consecutive_401_count > 0:
                logging.debug(f"🔄 Reset 401 counter for user {username}")
                info.consecutive_401_count = 0

    async def _ensure_valid_token(self, username: str) -> str | None:
        """Ensure the token is valid and return it.

        Args:
            username: Username associated with the token.

        Returns:
            The valid access token, or None if validation/refresh fails.
        """
        if not await self.is_token_valid(username):
            # Try refresh
            if not await self.refresh_token(username):
                return None

            # Re-check after refresh
            if not await self.is_token_valid(username):
                return None

        # Get the token
        info = await self.get_info(username)
        return info.access_token if info else None

    async def _set_invalid_callback(
        self, username: str, callback: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for token invalidation events.

        Args:
            username: Username associated with the token.
            callback: Async callable to invoke on token invalidation.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info:
                info.invalid_callback = callback

    async def is_token_valid(self, username: str) -> bool:
        """Check if the current token is valid and has required scopes.

        Performs validation and scope checking.

        Args:
            username: Username associated with the token.

        Returns:
            True if token is valid and has required scopes, False otherwise.
        """
        try:
            info = await self.get_info(username)
            if not info or not info.access_token:
                return False

            # Validate token and record scopes
            if not await self.validate_token(username, info.access_token):
                return False

            # Check scopes
            return await self.check_scopes(username, REQUIRED_SCOPES)

        except Exception as e:
            logging.debug(f"⚠️ Token validity check error for user {username}: {str(e)}")
            return False
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
            return self.tokens.get(username)

    async def _get_client(self, client_id: str, client_secret: str) -> TokenClient:
        """Retrieve or create a TokenClient for the given credentials.

        Uses caching to avoid creating multiple clients for the same credentials.

        Args:
            client_id: Twitch client ID.
            client_secret: Twitch client secret.

        Returns:
            TokenClient instance for the credentials.
        """
        async with self._client_cache_lock:
            key = (client_id, client_secret)
            cli = self._client_cache.get(key)
            if cli:
                return cli
            cli = TokenClient(client_id, client_secret, self.http_session)
            self._client_cache[key] = cli
            return cli

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
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if not info:
                return TokenOutcome.FAILED

            if self._should_skip_refresh(info, force_refresh):
                return TokenOutcome.VALID

            client = await self._get_client(info.client_id, info.client_secret)
            result, _ = await self._refresh_with_lock(
                client, info, username, force_refresh
            )
            return result.outcome

    # --- Internal helpers (extracted to reduce complexity) ---
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
        remaining = self._remaining_seconds(info)
        return (
            bool(info.expiry)
            and remaining is not None
            and remaining > TOKEN_REFRESH_THRESHOLD_SECONDS
        )

    async def reset_401_counter(self, username: str) -> None:
        """Reset the consecutive 401 error counter.

        Should be called when a successful operation occurs.

        Args:
            username: Username associated with the token.
        """
        async with self._tokens_lock:
            info = self.tokens.get(username)
            if info and info.consecutive_401_count > 0:
                logging.debug(f"🔄 Reset 401 counter for user {username}")
                info.consecutive_401_count = 0

    async def ensure_valid_token(self, username: str) -> str | None:
        """Ensure the token is valid and return it.

        Performs validation, refresh if needed, and scope checking.

        Args:
            username: Username associated with the token.

        Returns:
            The valid access token, or None if validation/refresh fails.
        """
        if not await self.is_token_valid(username):
            # Try refresh
            if not await self.refresh_token(username):
                return None

            # Re-check after refresh
            if not await self.is_token_valid(username):
                return None

        # Get the token
        info = await self.get_info(username)
        return info.access_token if info else None

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
        async with self._token_update_lock, info.refresh_lock:
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
                    await self._maybe_fire_invalidation_hook(username)
        # Fire hook if token actually changed. This is the single authoritative
        # location for firing update hooks to avoid double invocation (the
        # ensure_fresh wrapper deliberately does NOT fire the hook).
        await self._maybe_fire_update_hook(username, token_changed)
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

    async def _maybe_fire_update_hook(self, username: str, token_changed: bool) -> None:
        """Fire registered update hooks if the token has changed.

        Schedules hook coroutines to run asynchronously.

        Args:
            username: Username for which hooks should be fired.
            token_changed: Whether the token actually changed.

        Raises:
            ValueError: If hook scheduling fails.
            RuntimeError: If task creation fails.
        """
        if not token_changed:
            return
        async with self._hooks_lock:
            hooks = self._update_hooks.get(username) or []
        for hook in hooks:
            try:
                # Delegate creation to helper so both Ruff and VS Code recognize
                # the task is retained and exceptions logged.
                await self._create_retained_task(hook(), category="update_hook")
            except (ValueError, RuntimeError) as e:
                logging.debug(
                    f"⚠️ Update hook scheduling error user={username} type={type(e).__name__}"
                )

    async def _maybe_fire_invalidation_hook(self, username: str) -> None:
        """Fire registered invalidation hooks for token invalidation.

        Schedules hook coroutines to run asynchronously.

        Args:
            username: Username for which hooks should be fired.

        Raises:
            ValueError: If hook scheduling fails.
            RuntimeError: If task creation fails.
        """
        async with self._hooks_lock:
            hooks = self._invalidation_hooks.get(username) or []
        for hook in hooks:
            try:
                await self._create_retained_task(hook(), category="invalidation_hook")
            except (ValueError, RuntimeError) as e:
                logging.debug(
                    f"⚠️ Invalidation hook scheduling error user={username} type={type(e).__name__}"
                )

    async def _create_retained_task(
        self, coro: Coroutine[Any, Any, T], *, category: str
    ) -> asyncio.Task[T]:
        """Create and retain a background task with exception logging.

        Ensures the task handle is stored (preventing premature GC) and any
        exception is surfaced via structured logging.
        """
        # Sonar/VSC S7502: we retain task in self._hook_tasks; suppression justified.
        task: asyncio.Task[T] = asyncio.create_task(coro)  # NOSONAR S7502
        async with self._hooks_lock:
            self._hook_tasks.append(task)

        def _cb(t: asyncio.Task[T]) -> None:  # noqa: D401
            _ = asyncio.create_task(self._remove_hook_task(t, category))

        task.add_done_callback(_cb)
        return task

    async def _remove_hook_task(self, t: asyncio.Task[T], category: str) -> None:
        """Remove a completed hook task from the retained tasks list.

        Logs any exceptions from the task.

        Args:
            t: The asyncio Task to remove.
            category: Category of the hook task for logging.
        """
        async with self._hooks_lock:
            self._hook_tasks.remove(t)
        if t.cancelled():
            return
        exc = t.exception()
        if not exc:
            return
        try:
            logging.debug(
                f"⚠️ Retained background task error category={category} error={str(exc)} type={type(exc).__name__}"
            )
        except Exception as log_exc:  # pragma: no cover
            logging.debug(
                "TokenManager retained task logging failed: %s (%s)",
                log_exc,
                type(log_exc).__name__,
            )

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
        async with self._tokens_lock:
            info = self.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED
        now = time.time()
        if now - info.last_validation < TOKEN_MANAGER_VALIDATION_MIN_INTERVAL:
            return TokenOutcome.VALID
        if not info.expiry:
            return TokenOutcome.FAILED
        client = await self._get_client(info.client_id, info.client_secret)
        valid, expiry = await client._validate_remote(  # noqa: SLF001
            username, info.access_token
        )
        async with self._tokens_lock:
            info.last_validation = now
            if valid:
                info.expiry = expiry
                return TokenOutcome.VALID
            return TokenOutcome.FAILED

    # EventSub-specific methods for consolidated token management
    async def _validate_token_impl(self, username: str, access_token: str) -> bool:
        """Validate token and record scopes for EventSub operations.

        Args:
            username: Username associated with the token.
            access_token: Access token to validate.

        Returns:
            True if token is valid and scopes recorded, False otherwise.
        """
        if not access_token:
            return False

        try:
            # Get token info
            async with self._tokens_lock:
                info = self.tokens.get(username)
            if not info:
                return False

            # Use Twitch API to validate and get scopes
            validation = await self.api.validate_token(access_token)

            if not isinstance(validation, dict):
                return False

            raw_scopes = validation.get("scopes")
            if not isinstance(raw_scopes, list):
                return False

            # Record scopes in lowercase for consistent comparison
            recorded_scopes = {str(scope).lower() for scope in raw_scopes}

            # Update token info with scopes
            async with self._tokens_lock:
                if info in self.tokens.values():  # Ensure info is still valid
                    # Store scopes in token info for later retrieval
                    if not hasattr(info, "recorded_scopes"):
                        info.recorded_scopes = set()
                    info.recorded_scopes.update(recorded_scopes)

            return True

        except Exception:
            return False

    async def refresh_token(self, username: str, force_refresh: bool = False) -> bool:
        """Refresh token for EventSub operations.

        Args:
            username: Username to refresh token for.
            force_refresh: Force refresh regardless of expiry.

        Returns:
            True if refresh successful, False otherwise.
        """
        outcome = await self.ensure_fresh(username, force_refresh)
        return outcome.name != "FAILED"

    def _remaining_seconds(self, info: TokenInfo) -> float | None:
        """Calculate remaining seconds until token expiry.

        Args:
            info: TokenInfo object containing expiry information.

        Returns:
            Remaining seconds as float, or None if expiry is unknown.
        """
        if not info.expiry:
            return None
        return (info.expiry - datetime.now(UTC)).total_seconds()

    async def _background_refresh_loop(self) -> None:
        """Background loop for periodic token validation and refresh.

        Runs continuously while the manager is running, checking all tokens
        and refreshing as needed.

        Raises:
            RuntimeError: If background processing fails.
            OSError: If system-level errors occur.
            ValueError: If invalid data is encountered.
            aiohttp.ClientError: If network requests fail.
        """
        base = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP
        last_loop = time.time()
        while self.running:
            try:
                now = time.time()
                drift = now - last_loop
                drifted = drift > (base * 3)
                if drifted:
                    logging.info(
                        f"⏱️ Token manager loop drift detected drift={int(drift)}s base={base}s"
                    )
                async with self._tokens_lock:
                    users = list(self.tokens.items())
                users = [(u, info) for u, info in users if u not in self._paused_users]

                async def _limited_process(
                    username: str, info: TokenInfo, force_proactive: bool
                ) -> None:
                    async with self._concurrent_semaphore:
                        await self._process_single_background(
                            username, info, force_proactive=force_proactive
                        )

                if users:
                    start_time = time.time()
                    tasks = [
                        _limited_process(username, info, drifted)
                        for username, info in users
                    ]
                    await asyncio.gather(*tasks)
                    elapsed = time.time() - start_time
                    logging.info(
                        f"🔄 Background refresh processed {len(users)} users concurrently in {elapsed:.2f}s"
                    )
                last_loop = now
                await asyncio.sleep(base * _jitter_rng.uniform(0.5, 1.5))
            except (RuntimeError, OSError, ValueError, aiohttp.ClientError) as e:
                logging.error(f"💥 Background token manager loop error: {str(e)}")
                await asyncio.sleep(base * 2)

    async def _process_single_background(
        self, username: str, info: TokenInfo, *, force_proactive: bool = False
    ) -> None:
        """Handle refresh/validation logic for a single user (extracted to reduce complexity)."""
        remaining = self._remaining_seconds(info)
        self._log_remaining_detail(username, remaining)
        # Unified unknown-expiry + periodic validation resolution.
        remaining = await self._maybe_periodic_or_unknown_resolution(
            username, info, remaining
        )
        if remaining is None:
            return
        if remaining < 0:
            async with info.refresh_lock:
                info.state = TokenState.EXPIRED
            logging.warning(
                f"⚠️ Unexpected expired state detected user={username} remaining={remaining}"
            )
            await self.ensure_fresh(username, force_refresh=True)
            return
        trigger_threshold = TOKEN_REFRESH_THRESHOLD_SECONDS
        # If the loop drifted, give ourselves more headroom by doubling threshold.
        if force_proactive:
            trigger_threshold *= 2
        if remaining <= trigger_threshold:
            # If drift triggered and we're only refreshing early due to doubled threshold,
            # force the refresh so _should_skip_refresh does not ignore it.
            if force_proactive and remaining > TOKEN_REFRESH_THRESHOLD_SECONDS:
                await self.ensure_fresh(username, force_refresh=True)
            else:
                await self.ensure_fresh(username)

    async def _maybe_periodic_or_unknown_resolution(
        self, username: str, info: TokenInfo, remaining: float | None
    ) -> float | None:
        """Resolve unknown expiry or perform periodic validation.

        Returns (possibly updated) remaining seconds (None if still unknown).
        Always logs both remaining_seconds and remaining_human for periodic events.
        """
        # Unknown expiry path first.
        if info.expiry is None:
            await self._handle_unknown_expiry(username)
            return self._remaining_seconds(info)
        # Periodic validation check.
        try:
            now = time.time()
            if now - info.last_validation < TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL:
                return remaining
            outcome = await self.validate(username)
            updated_remaining = self._remaining_seconds(info)
            if outcome == TokenOutcome.VALID:
                if updated_remaining is not None:
                    human_new = format_duration(max(0, int(updated_remaining)))
                    logging.info(
                        f"✅ Periodic remote token validation ok for user {username} ({human_new} remaining)"
                    )
                return updated_remaining
            # Failure -> forced refresh.
            pre_seconds = (
                int(updated_remaining) if updated_remaining is not None else None
            )
            pre_human = (
                format_duration(max(0, pre_seconds))
                if pre_seconds is not None
                else "unknown"
            )
            logging.error(
                f"❌ Periodic remote token validation failed for user {username} ({pre_human} remaining pre-refresh, {pre_seconds}s)"
            )
            ref_outcome = await self.ensure_fresh(username, force_refresh=True)
            post_remaining = self._remaining_seconds(info)
            post_seconds = int(post_remaining) if post_remaining is not None else None
            post_human = (
                format_duration(max(0, post_seconds))
                if post_seconds is not None
                else "unknown"
            )
            logging.info(
                f"🔄 Forced refresh after failed periodic remote validation for user {username} outcome={ref_outcome.value} ({post_human} remaining, {post_seconds}s)"
            )
            return post_remaining
        except (aiohttp.ClientError, ValueError, RuntimeError) as e:
            logging.warning(
                f"⚠️ Periodic remote token validation error for user {username} type={type(e).__name__} error={str(e)}"
            )
            return self._remaining_seconds(info)

    def _log_remaining_detail(self, username: str, remaining: float | None) -> None:
        """Log detailed remaining token validity time for observability.

        Args:
            username: Username associated with the token.
            remaining: Remaining seconds until expiry, or None if unknown.
        """
        # Emit remaining time every cycle for observability (even when no refresh triggered).
        if remaining is None:
            logging.debug(
                f"❔ Token expiry unknown (will validate / refresh) user={username} remaining_seconds=None"
            )
            return
        int_remaining = int(remaining)
        human = format_duration(int(max(0, int_remaining)))
        if int_remaining <= 900:
            icon = "🚨"
        elif int_remaining <= 3600:
            icon = "⏰"
        elif int_remaining <= 2 * 3600:
            icon = "⌛"
        else:
            icon = "🔐"
        # Expiry timestamp not included in human message (simplified per request).
        # Build a clearer human message: explicitly mention token remaining time (no extra parenthetical details).
        logging.debug(
            f"{icon} Access token validity: {human} remaining user={username} remaining_seconds={int_remaining}"
        )

    async def _handle_unknown_expiry(self, username: str) -> None:
        """Resolve unknown expiry with capped forced refresh attempts (max 3) using exponential backoff."""
        outcome = await self.ensure_fresh(username, force_refresh=False)
        async with self._tokens_lock:
            info_ref = self.tokens.get(username)
        if not info_ref:
            return
        if info_ref.expiry is None:
            async with self._tokens_lock:
                if info_ref.forced_unknown_attempts < 3:
                    info_ref.forced_unknown_attempts += 1
                    delay = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP * (
                        2 ** (info_ref.forced_unknown_attempts - 1)
                    )
                    await asyncio.sleep(delay)
                    forced = await self.ensure_fresh(username, force_refresh=True)
                    if forced == TokenOutcome.FAILED:
                        logging.warning(
                            f"⚠️ Forced refresh attempt failed resolving unknown expiry user={username} attempt={info_ref.forced_unknown_attempts}"
                        )
                    else:
                        logging.info(
                            f"✅ Forced refresh resolved unknown expiry user={username} attempt={info_ref.forced_unknown_attempts}"
                        )
                    async with self._tokens_lock:
                        info_ref.forced_unknown_attempts = 0
        else:
            async with self._tokens_lock:
                if info_ref.forced_unknown_attempts:
                    info_ref.forced_unknown_attempts = 0
        async with self._tokens_lock:
            if outcome == TokenOutcome.FAILED and info_ref.expiry is None:
                logging.warning(
                    f"⚠️ Validation failed with unknown expiry user={username}"
                )
