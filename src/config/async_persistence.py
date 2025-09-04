"""Async helpers for config persistence.

Centralizes the pattern of running blocking config file updates inside
``run_in_executor`` so callers don't repeat boilerplate. This also provides a
single place to later introduce batching / coalescing of rapid successive
writes (for example multiple flag toggles in quick succession) without
changing call sites.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..logs.logger import logger
from .core import update_user_in_config

__all__ = [
    "async_update_user_in_config",
    "queue_user_update",
    "flush_pending_updates",
]

# --- Debounced batching infrastructure ---

_PENDING: dict[str, dict[str, Any]] = {}
_FLUSH_TASK: asyncio.Task[Any] | None = None
_LOCK = asyncio.Lock()
_DEBOUNCE_SECONDS = 0.25  # adjustable small delay to coalesce bursts

# Per-user write locks so a direct immediate write and a batched flush do not
# interleave for the same username (e.g., rapid toggle paths mixing queue and
# explicit persistence). These are created lazily to avoid unbounded growth.
_USER_LOCKS: dict[str, tuple[asyncio.Lock, float]] = {}
_USER_LOCKS_LOCK = asyncio.Lock()
_LOCK_TTL_SECONDS = 24 * 3600  # prune inactive user locks after 24h


async def _get_user_lock(username: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for a username.

    A dedicated small lock registry prevents write interleaving on the same
    logical record while allowing unrelated users to persist concurrently in
    future if parallelism is later introduced. (Current implementation keeps
    sequential writes, but this preserves correctness if that changes.)
    """
    # Normalize once to lower; callers already lowercase but be defensive.
    uname = username.lower()
    now = time.time()
    async with _USER_LOCKS_LOCK:
        entry = _USER_LOCKS.get(uname)
        if entry is None:
            lock = asyncio.Lock()
            _USER_LOCKS[uname] = (lock, now)
            return lock
        lock, _ts = entry
        _USER_LOCKS[uname] = (lock, now)
        return lock


async def _prune_user_locks() -> None:
    now = time.time()
    async with _USER_LOCKS_LOCK:
        stale = [
            u for u, (_l, ts) in _USER_LOCKS.items() if now - ts > _LOCK_TTL_SECONDS
        ]
        for u in stale:
            _USER_LOCKS.pop(u, None)
        if stale:
            try:
                logger.log_event(
                    "config",
                    "user_lock_prune",
                    pruned=len(stale),
                    remaining=len(_USER_LOCKS),
                )
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "config", "user_lock_prune_log_error", level=10, error=str(e)
                )


async def _flush(config_file: str) -> None:
    global _FLUSH_TASK
    async with _LOCK:
        pending = list(_PENDING.values())
        _PENDING.clear()
        _FLUSH_TASK = None
    if not pending:
        return
    _log_batch_start(len(pending))
    failures = await _persist_batch(pending, config_file)
    _log_batch_result(failures, len(pending))
    # Opportunistically prune inactive locks after a batch flush
    try:
        await _prune_user_locks()
    except Exception as e:  # noqa: BLE001
        logger.log_event("config", "batch_flush_prune_error", level=10, error=str(e))


def _log_batch_start(count: int) -> None:
    try:  # noqa: SIM105
        logger.log_event(
            "config",
            "batch_flush",
            count=count,
            debounce_seconds=_DEBOUNCE_SECONDS,
        )
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "config",
            "batch_flush_log_error",
            level=30,
            error=str(e),
        )


def _log_batch_result(failures: int, attempted: int) -> None:
    if failures:
        logger.log_event(
            "config",
            "batch_flush_partial_failures",
            level=30,
            failures=failures,
            attempted=attempted,
        )


async def _persist_batch(pending: list[dict[str, Any]], config_file: str) -> int:
    failures = 0
    for uc in pending:
        uname = str(uc.get("username", "")).lower()
        per_user_lock: asyncio.Lock | None = None
        if uname:
            per_user_lock = await _get_user_lock(uname)
        try:
            loop = asyncio.get_event_loop()
            if per_user_lock:
                async with per_user_lock:
                    await loop.run_in_executor(
                        None, update_user_in_config, uc, config_file
                    )
            else:
                await loop.run_in_executor(None, update_user_in_config, uc, config_file)
        except Exception as e:  # noqa: BLE001
            failures += 1
            if failures <= 3:
                logger.log_event(
                    "config",
                    "batch_item_write_error",
                    level=30,
                    username=uname or uc.get("username"),
                    error=str(e),
                )
    return failures


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
