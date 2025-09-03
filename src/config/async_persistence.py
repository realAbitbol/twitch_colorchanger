"""Async helpers for config persistence.

Centralizes the pattern of running blocking config file updates inside
``run_in_executor`` so callers don't repeat boilerplate. This also provides a
single place to later introduce batching / coalescing of rapid successive
writes (for example multiple flag toggles in quick succession) without
changing call sites.
"""

from __future__ import annotations

import asyncio
from typing import Any

from logs.logger import logger

from .core import update_user_in_config

__all__ = [
    "async_update_user_in_config",
    "queue_user_update",
    "flush_pending_updates",
]

# --- Debounced batching infrastructure ---

_PENDING: dict[str, dict[str, Any]] = {}
_FLUSH_TASK: asyncio.Task | None = None
_LOCK = asyncio.Lock()
_DEBOUNCE_SECONDS = 0.25  # adjustable small delay to coalesce bursts

# Per-user write locks so a direct immediate write and a batched flush do not
# interleave for the same username (e.g., rapid toggle paths mixing queue and
# explicit persistence). These are created lazily to avoid unbounded growth.
_USER_LOCKS: dict[str, asyncio.Lock] = {}
_USER_LOCKS_LOCK = asyncio.Lock()


async def _get_user_lock(username: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for a username.

    A dedicated small lock registry prevents write interleaving on the same
    logical record while allowing unrelated users to persist concurrently in
    future if parallelism is later introduced. (Current implementation keeps
    sequential writes, but this preserves correctness if that changes.)
    """
    # Normalize once to lower; callers already lowercase but be defensive.
    uname = username.lower()
    async with _USER_LOCKS_LOCK:
        lock = _USER_LOCKS.get(uname)
        if lock is None:
            lock = asyncio.Lock()
            _USER_LOCKS[uname] = lock
        return lock


async def _flush(config_file: str) -> None:
    global _FLUSH_TASK
    async with _LOCK:
        pending = list(_PENDING.values())
        _PENDING.clear()
        _FLUSH_TASK = None
    if not pending:
        return
    # Log batch meta; ignore only logger internal failures.
    try:  # noqa: SIM105
        logger.log_event(
            "config",
            "batch_flush",
            count=len(pending),
            debounce_seconds=_DEBOUNCE_SECONDS,
        )
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "config",
            "batch_flush_log_error",
            level=30,
            error=str(e),
        )
    # Sequentially persist each aggregated user config. We intentionally do
    # not parallelize to avoid interleaving writes to the same file.
    failures = 0
    for uc in pending:
        uname = str(uc.get("username", "")).lower()
        # Acquire per-user lock if username present; skip if missing.
        per_user_lock: asyncio.Lock | None = None
        if uname:
            per_user_lock = await _get_user_lock(uname)
        try:
            if per_user_lock:
                async with per_user_lock:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, update_user_in_config, uc, config_file
                    )
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, update_user_in_config, uc, config_file)
        except Exception as e:  # noqa: BLE001
            failures += 1
            if failures <= 3:  # cap detailed logs to avoid spam
                logger.log_event(
                    "config",
                    "batch_item_write_error",
                    level=30,
                    username=uname or uc.get("username"),
                    error=str(e),
                )
    if failures:
        logger.log_event(
            "config",
            "batch_flush_partial_failures",
            level=30,
            failures=failures,
            attempted=len(pending),
        )


async def _schedule_flush(config_file: str) -> None:
    await asyncio.sleep(_DEBOUNCE_SECONDS)
    await _flush(config_file)


async def queue_user_update(user_config: dict[str, Any], config_file: str) -> None:
    """Queue a user update for debounced batch persistence.

    Multiple rapid calls within the debounce window collapse into a single
    write per username (last-wins merge at dict level).
    """
    uname = str(user_config.get("username", "")).lower()
    if not uname:
        return
    async with _LOCK:
        existing = _PENDING.get(uname, {})
        merged = {**existing, **user_config}
        _PENDING[uname] = merged
        global _FLUSH_TASK
        if _FLUSH_TASK is None or _FLUSH_TASK.done():
            _FLUSH_TASK = asyncio.create_task(_schedule_flush(config_file))


async def flush_pending_updates(config_file: str) -> None:
    """Force an immediate flush (e.g., before shutdown)."""
    await _flush(config_file)


async def async_update_user_in_config(
    user_config: dict[str, Any], config_file: str
) -> bool:
    """Run ``update_user_in_config`` in the default thread executor.

    Returns the boolean result from the underlying synchronous function.
    """
    loop = asyncio.get_event_loop()
    uname = str(user_config.get("username", "")).lower()
    if uname:
        lock = await _get_user_lock(uname)
        async with lock:
            return await loop.run_in_executor(
                None, update_user_in_config, user_config, config_file
            )
    # Fallback if username missing (should be rare / non-critical paths).
    return await loop.run_in_executor(
        None, update_user_in_config, user_config, config_file
    )
