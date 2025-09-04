"""Token manager (moved from token_manager.py)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from secrets import SystemRandom
from typing import Any, TypeVar

import aiohttp

from ..constants import (
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from ..logs.logger import logger
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
                # Propagate cancellation upwards; restart logic should honor this.
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
        self.background_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.log_event("token_manager", "start")
        await asyncio.sleep(0)

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
                else:
                    raise
            finally:
                self.background_task = None

    def register(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        expiry: datetime | None,
    ) -> None:
        info = self.tokens.get(username)
        if info:
            info.access_token = access_token
            info.refresh_token = refresh_token
            info.client_id = client_id
            info.client_secret = client_secret
            info.expiry = expiry
            info.state = TokenState.FRESH
        else:
            self.tokens[username] = TokenInfo(
                username=username,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                expiry=expiry,
            )
        self.logger.log_event("token_manager", "registered", user=username)

    def register_update_hook(
        self, username: str, hook: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a coroutine hook invoked after a successful token refresh.

        The hook should perform persistence of updated tokens. Errors are suppressed
        at invocation time to avoid disrupting refresh cycles.
        """
        self._update_hooks[username] = hook

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
        result, token_changed = await self._refresh_with_lock(
            client, info, username, force_refresh
        )
        self._maybe_fire_update_hook(username, token_changed)
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
        while self.running:
            try:
                for username, info in self.tokens.items():
                    remaining = self._remaining_seconds(info)
                    if remaining is None or remaining < 0:
                        info.state = TokenState.EXPIRED
                        continue
                    if remaining < TOKEN_REFRESH_THRESHOLD_SECONDS:
                        await self.ensure_fresh(username)
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
