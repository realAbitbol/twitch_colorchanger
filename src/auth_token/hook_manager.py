"""Hook management for token updates and invalidations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import TokenManager


class HookManager:
    """Manages registration and firing of update and invalidation hooks."""

    def __init__(self, manager: TokenManager) -> None:
        self.manager = manager
        self._hooks_lock = asyncio.Lock()
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

    async def maybe_fire_update_hook(self, username: str, token_changed: bool) -> None:
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

    async def maybe_fire_invalidation_hook(self, username: str) -> None:
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
        self, coro: Coroutine[Any, Any, Any], *, category: str
    ) -> asyncio.Task[Any]:
        """Create and retain a background task with exception logging.

        Ensures the task handle is stored (preventing premature GC) and any
        exception is surfaced via structured logging.
        """
        # Sonar/VSC S7502: we retain task in self._hook_tasks; suppression justified.
        task: asyncio.Task[Any] = asyncio.create_task(coro)  # NOSONAR S7502
        async with self._hooks_lock:
            self._hook_tasks.append(task)

        def _cb(t: asyncio.Task[Any]) -> None:  # noqa: D401
            _ = asyncio.create_task(self._remove_hook_task(t, category))

        task.add_done_callback(_cb)
        return task

    async def _remove_hook_task(self, t: asyncio.Task[Any], category: str) -> None:
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
