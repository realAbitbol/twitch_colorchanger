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

from ..constants import (
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL,
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from ..logs.logger import logger
from ..utils import format_duration
from .client import TokenClient, TokenOutcome, TokenResult

T = TypeVar("T")

_jitter_rng = SystemRandom()


class TokenState(Enum):
    FRESH = "fresh"
    STALE = "stale"
    REFRESHING = "refreshing"
    EXPIRED = "expired"


@dataclass
class TokenInfo:
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
    _instance = None  # Simple singleton; not thread-safe by design (single event loop).
    background_task: asyncio.Task[Any] | None

    def __new__(cls, http_session: aiohttp.ClientSession) -> TokenManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, http_session: aiohttp.ClientSession):
        """Initialize the token manager singleton instance."""
        # Guard: if already initialized (singleton), skip re-initialization.
        if getattr(self, "_inst_initialized", False):  # pragma: no cover - simple guard
            return
        # Core state
        self.http_session = http_session
        self.tokens: dict[str, TokenInfo] = {}
        self.background_task: asyncio.Task[Any] | None = None
        self.running = False
        self.logger = logger
        self._client_cache: dict[tuple[str, str], TokenClient] = {}
        # Registered per-user async persistence hooks (called after token refresh).
        self._update_hooks: dict[str, Callable[[], Coroutine[Any, Any, None]]] = {}
        # Retained background tasks (e.g. persistence hooks) to prevent premature GC.
        self._hook_tasks: list[asyncio.Task[Any]] = []
        # Mark as initialized to avoid repeating work on future constructions.
        self._inst_initialized = True

    async def start(self) -> None:
        if self.running:
            return
        # Defensive: if a previous background task is still lingering (e.g. rapid
        # stop/start where stop hasn't fully awaited cancellation yet), ensure it
        # is cancelled and awaited to avoid multiple loops.
        if self.background_task and not self.background_task.done():
            self.logger.log_event(
                "token_manager",
                "stale_background_detected",
                level=logging.DEBUG,
                human="Cancelling stale background task before restart",
            )
            try:
                self.background_task.cancel()
                await self.background_task
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.logger.log_event(
                    "token_manager",
                    "stale_background_error",
                    level=logging.DEBUG,
                    error=str(e),
                )
            finally:
                self.background_task = None
        self.running = True
        # Initial validation pass before launching background loop
        await self._initial_validation_pass()
        self.background_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.log_event("token_manager", "start", level=10)
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
        for username, info in self.tokens.items():
            await self._initial_validate_user(username, info)

    async def _initial_validate_user(self, username: str, info: TokenInfo) -> None:
        try:
            if info.expiry is None:
                self.logger.log_event(
                    "token_manager",
                    "startup_validation_skipped_unknown_expiry",
                    user=username,
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
                    self.logger.log_event(
                        "token_manager",
                        "startup_validated_and_refreshed"
                        if ref == TokenOutcome.REFRESHED
                        else "startup_validated_within_threshold",
                        user=username,
                        remaining=int(remaining),
                        refresh_outcome=ref.value,
                    )
                else:
                    self.logger.log_event(
                        "token_manager",
                        "startup_validated_ok",
                        user=username,
                        remaining=int(remaining),
                    )
            else:
                ref = await self.ensure_fresh(username, force_refresh=True)
                self.logger.log_event(
                    "token_manager",
                    "startup_validation_forced_refresh",
                    user=username,
                    refresh_outcome=ref.value,
                )
        except Exception as e:  # noqa: BLE001
            self.logger.log_event(
                "token_manager",
                "startup_validation_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
                level=logging.DEBUG,
            )

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except Exception as e:  # noqa: BLE001
                if isinstance(e, asyncio.CancelledError):
                    self.logger.log_event(
                        "token_manager",
                        "background_cancelled",
                        level=logging.DEBUG,
                        human="Background loop cancelled",
                    )
                else:  # Re-raise unexpected exceptions
                    raise
            finally:
                self.background_task = None

    def register_update_hook(
        self, username: str, hook: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a coroutine hook invoked after a successful token refresh.

        The hook should perform persistence of updated tokens. Errors are suppressed
        at invocation time to avoid disrupting refresh cycles.
        """
        self._update_hooks[username] = hook

    def register_eventsub_backend(self, username: str, backend: Any) -> None:
        """Register EventSub chat backend for automatic token propagation.

        Creates an update hook that calls backend.update_access_token(new_token)
        after successful refresh. Silently ignored if backend lacks method.
        """
        if not hasattr(backend, "update_access_token"):
            return

        async def _propagate() -> None:  # coroutine required by register_update_hook
            info = self.tokens.get(username)
            if not info or not info.access_token:
                return
            try:
                backend.update_access_token(info.access_token)
            except Exception as e:  # noqa: BLE001
                self.logger.log_event(
                    "token_manager",
                    "eventsub_token_propagate_error",
                    level=30,
                    user=username,
                    error=str(e),
                )
            # tiny await to satisfy linters that expect async use
            await asyncio.sleep(0)

        self.register_update_hook(username, _propagate)

    def _upsert_token_info(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        expiry: datetime | None,
    ) -> TokenInfo:
        """Internal helper to insert/update token state (called by BotRegistrar)."""
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
                remaining = int((expiry - datetime.now()).total_seconds())
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
                remaining = int((expiry - datetime.now()).total_seconds())
                if remaining > 0:
                    info.original_lifetime = remaining
        return info

    def remove(self, username: str) -> bool:
        """Remove a user from token tracking (e.g., config removal)."""
        if username in self.tokens:
            del self.tokens[username]
            self.logger.log_event(
                "token_manager", "removed", level=logging.DEBUG, user=username
            )
            return True
        return False

    def prune(self, active_usernames: set[str]) -> int:
        """Prune tokens not in active set; return count removed."""
        to_remove = [u for u in self.tokens if u not in active_usernames]
        for u in to_remove:
            del self.tokens[u]
        if to_remove:
            self.logger.log_event(
                "token_manager",
                "pruned",
                removed=len(to_remove),
                remaining=len(self.tokens),
            )
        return len(to_remove)

    def get_info(self, username: str) -> TokenInfo | None:
        return self.tokens.get(username)

    def _get_client(self, client_id: str, client_secret: str) -> TokenClient:
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
        info = self.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED

        if self._should_skip_refresh(info, force_refresh):
            return TokenOutcome.VALID

        client = self._get_client(info.client_id, info.client_secret)
        result, _ = await self._refresh_with_lock(client, info, username, force_refresh)
        return result.outcome

    # --- Internal helpers (extracted to reduce complexity) ---
    def _should_skip_refresh(self, info: TokenInfo, force_refresh: bool) -> bool:
        if force_refresh:
            return False
        remaining = self._remaining_seconds(info)
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
                info.state = TokenState.EXPIRED
        # Fire hook if token actually changed. This is the single authoritative
        # location for firing update hooks to avoid double invocation (the
        # ensure_fresh wrapper deliberately does NOT fire the hook).
        self._maybe_fire_update_hook(username, token_changed)
        return result, token_changed

    def _apply_successful_refresh(self, info: TokenInfo, result: TokenResult) -> None:
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
            remaining = int((info.expiry - datetime.now()).total_seconds())
            if remaining > 0:
                info.original_lifetime = remaining

    def _maybe_fire_update_hook(self, username: str, token_changed: bool) -> None:
        if not token_changed:
            return
        hook = self._update_hooks.get(username)
        if not hook:
            return
        try:
            # Delegate creation to helper so both Ruff and VS Code recognize
            # the task is retained and exceptions logged.
            self._create_retained_task(hook(), category="update_hook")
        except Exception as e:  # noqa: BLE001
            self.logger.log_event(
                "token_manager",
                "update_hook_error",
                level=logging.DEBUG,
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )

    def _create_retained_task(
        self, coro: Coroutine[Any, Any, T], *, category: str
    ) -> asyncio.Task[T]:
        """Create and retain a background task with exception logging.

        Ensures the task handle is stored (preventing premature GC) and any
        exception is surfaced via structured logging.
        """
        # Sonar/VSC S7502: we retain task in self._hook_tasks; suppression justified.
        task: asyncio.Task[T] = asyncio.create_task(coro)  # NOSONAR S7502
        self._hook_tasks.append(task)

        def _cb(t: asyncio.Task[T]) -> None:  # noqa: D401
            if t.cancelled():
                return
            exc = t.exception()
            if not exc:
                return
            try:
                self.logger.log_event(
                    "token_manager",
                    "retained_task_error",
                    level=logging.DEBUG,
                    category=category,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            except Exception as log_exc:  # pragma: no cover
                logging.debug(
                    "TokenManager retained task logging failed: %s (%s)",
                    log_exc,
                    type(log_exc).__name__,
                )

        task.add_done_callback(_cb)
        return task

    async def validate(self, username: str) -> TokenOutcome:
        info = self.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED
        now = time.time()
        if now - info.last_validation < TOKEN_MANAGER_VALIDATION_MIN_INTERVAL:
            return TokenOutcome.VALID
        if not info.expiry:
            return TokenOutcome.FAILED
        client = self._get_client(info.client_id, info.client_secret)
        valid, expiry = await client._validate_remote(  # noqa: SLF001
            username, info.access_token
        )
        info.last_validation = now
        if valid:
            info.expiry = expiry
            return TokenOutcome.VALID
        return TokenOutcome.FAILED

    def _remaining_seconds(self, info: TokenInfo) -> float | None:
        if not info.expiry:
            return None
        return (info.expiry - datetime.now()).total_seconds()

    async def _background_refresh_loop(self) -> None:
        base = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP
        last_loop = time.time()
        while self.running:
            try:
                now = time.time()
                drift = now - last_loop
                drifted = drift > (base * 3)
                if drifted:
                    self.logger.log_event(
                        "token_manager",
                        "loop_drift_detected",
                        drift_seconds=int(drift),
                        base_sleep=base,
                    )
                for username, info in self.tokens.items():
                    await self._process_single_background(
                        username, info, force_proactive=drifted
                    )
                last_loop = now
                await asyncio.sleep(base * _jitter_rng.uniform(0.5, 1.5))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.logger.log_event(
                    "token_manager",
                    "background_error",
                    level=logging.ERROR,
                    error=str(e),
                )
                await asyncio.sleep(base * 2)

    async def _process_single_background(
        self, username: str, info: TokenInfo, *, force_proactive: bool = False
    ) -> None:
        """Handle refresh/validation logic for a single user (extracted to reduce complexity)."""
        remaining = self._remaining_seconds(info)
        self._log_remaining_detail(username, info, remaining)
        # Unified unknown-expiry + periodic validation resolution.
        remaining = await self._maybe_periodic_or_unknown_resolution(
            username, info, remaining
        )
        if remaining is None:
            return
        if remaining < 0:
            info.state = TokenState.EXPIRED
            self.logger.log_event(
                "token_manager",
                "unexpected_expired_state",
                user=username,
                remaining=remaining,
            )
            await self.ensure_fresh(username, force_refresh=True)
            return
        trigger_threshold = TOKEN_REFRESH_THRESHOLD_SECONDS
        # If the loop drifted, give ourselves more headroom by doubling threshold.
        if force_proactive:
            trigger_threshold *= 2
        if remaining < trigger_threshold:
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
                    self.logger.log_event(
                        "token_manager",
                        "periodic_validation_ok",
                        user=username,
                        remaining_human=human_new,
                        remaining_seconds=int(updated_remaining),
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
            self.logger.log_event(
                "token_manager",
                "periodic_validation_failed",
                user=username,
                remaining_human=pre_human,
                remaining_seconds=pre_seconds,
            )
            ref_outcome = await self.ensure_fresh(username, force_refresh=True)
            post_remaining = self._remaining_seconds(info)
            post_seconds = int(post_remaining) if post_remaining is not None else None
            post_human = (
                format_duration(max(0, post_seconds))
                if post_seconds is not None
                else "unknown"
            )
            self.logger.log_event(
                "token_manager",
                "periodic_validation_forced_refresh",
                user=username,
                refresh_outcome=ref_outcome.value,
                new_remaining_human=post_human,
                new_remaining_seconds=post_seconds,
            )
            return post_remaining
        except Exception as e:  # noqa: BLE001
            self.logger.log_event(
                "token_manager",
                "periodic_validation_error",
                user=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return self._remaining_seconds(info)

    def _log_remaining_detail(
        self, username: str, info: TokenInfo, remaining: float | None
    ) -> None:
        # Emit remaining time every cycle for observability (even when no refresh triggered).
        if remaining is None:
            self.logger.log_event(
                "token_manager",
                "remaining_time_detail",
                level=logging.DEBUG,
                user=username,
                message="❔ Token expiry unknown (will validate / refresh)",
                remaining_seconds=None,
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
        if info.expiry:
            # Still normalize timezone (side-effect free; retained if future logging re-introduces expiry).
            exp_dt = info.expiry
            if exp_dt.tzinfo is None:
                _ = exp_dt.replace(tzinfo=UTC)
            else:
                _ = exp_dt.astimezone(UTC)
        # Build a clearer human message: explicitly mention token remaining time (no extra parenthetical details).
        self.logger.log_event(
            "token_manager",
            "remaining_time_detail",
            level=logging.DEBUG,
            user=username,
            message=f"{icon} Access token validity: {human} remaining",
            remaining_seconds=int_remaining,
        )

    async def _handle_unknown_expiry(self, username: str) -> None:
        """Resolve unknown expiry with capped forced refresh attempts (max 3)."""
        outcome = await self.ensure_fresh(username, force_refresh=False)
        info_ref = self.tokens.get(username)
        if not info_ref:
            return
        if info_ref.expiry is None:
            if info_ref.forced_unknown_attempts < 3:
                info_ref.forced_unknown_attempts += 1
                forced = await self.ensure_fresh(username, force_refresh=True)
                if forced == TokenOutcome.FAILED:
                    self.logger.log_event(
                        "token_manager",
                        "expiry_unknown_forced_refresh_failed",
                        user=username,
                        attempt=info_ref.forced_unknown_attempts,
                        max_attempts=3,
                    )
                else:
                    self.logger.log_event(
                        "token_manager",
                        "expiry_unknown_forced_refresh_success",
                        user=username,
                        attempt=info_ref.forced_unknown_attempts,
                        max_attempts=3,
                    )
            else:
                self.logger.log_event(
                    "token_manager",
                    "expiry_unknown_forced_refresh_exhausted",
                    level=logging.WARNING,
                    user=username,
                    max_attempts=3,
                )
        else:
            if info_ref.forced_unknown_attempts:
                info_ref.forced_unknown_attempts = 0
        if outcome == TokenOutcome.FAILED and info_ref.expiry is None:
            self.logger.log_event(
                "token_manager",
                "expiry_unknown_validation_failed",
                user=username,
            )
