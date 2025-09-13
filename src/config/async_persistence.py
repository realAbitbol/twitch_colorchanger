"""Async helpers for config persistence.

Centralizes the pattern of running blocking config file updates inside
``run_in_executor`` so callers don't repeat boilerplate. This also provides a
single place to later introduce batching / coalescing of rapid successive
writes (for example multiple flag toggles in quick succession) without
changing call sites.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

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

    Args:
        username: The username to get the lock for.

    Returns:
        The asyncio.Lock associated with the username.
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
    """Prune inactive user locks after TTL to prevent unbounded growth."""
    now = time.time()
    async with _USER_LOCKS_LOCK:
        stale = [
            u for u, (_l, ts) in _USER_LOCKS.items() if now - ts > _LOCK_TTL_SECONDS
        ]
        for u in stale:
            _USER_LOCKS.pop(u, None)
        if stale:
            try:
                # Use placeholder names matching event template (removed, remaining)
                logging.info(
                    f"🧹 Pruned user locks removed={len(stale)} remaining={len(_USER_LOCKS)}"
                )
            except Exception as e:  # noqa: BLE001
                logging.debug(f"⚠️ Error logging user lock prune details: {str(e)}")


async def _flush(config_file: str) -> None:
    """Flush pending user updates to the config file.

    Args:
        config_file: Path to the configuration file.
    """
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
        logging.debug(f"⚠️ Error pruning user locks: {str(e)}")


def _log_batch_start(count: int) -> None:
    """Log the start of a batch flush operation.

    Args:
        count: Number of pending updates.
    """
    try:  # noqa: SIM105
        logging.info(
            f"📤 Config batch flush count={count} debounce_seconds={_DEBOUNCE_SECONDS}"
        )
    except Exception as e:  # noqa: BLE001
        logging.warning(f"⚠️ Error logging batch flush details: {str(e)}")


def _log_batch_result(failures: int, attempted: int) -> None:
    """Log the result of a batch flush operation.

    Args:
        failures: Number of failed updates.
        attempted: Total number of attempted updates.
    """
    if failures:
        logging.warning(
            f"⚠️ Batch flush had partial failures count={failures} attempted={attempted}"
        )


async def _persist_batch(pending: list[dict[str, Any]], config_file: str) -> int:
    """Persist a batch of user configurations to the config file.

    Args:
        pending: List of user config dictionaries to persist.
        config_file: Path to the configuration file.

    Returns:
        Number of failed persistence operations.
    """
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
                logging.warning(
                    f"⚠️ Error writing batch item user={uname or uc.get('username')}: {str(e)}"
                )
    return failures


async def _schedule_flush(config_file: str) -> None:
    """Schedule a flush after the debounce delay.

    Args:
        config_file: Path to the configuration file.
    """
    await asyncio.sleep(_DEBOUNCE_SECONDS)
    await _flush(config_file)


async def queue_user_update(user_config: dict[str, Any], config_file: str) -> None:
    """Queue a user update for debounced batch persistence.

    Multiple rapid calls within the debounce window collapse into a single
    write per username (last-wins merge at dict level).

    Args:
        user_config: Dictionary containing user configuration data.
        config_file: Path to the configuration file.
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
    """Force an immediate flush (e.g., before shutdown).

    Args:
        config_file: Path to the configuration file.
    """
    await _flush(config_file)


async def async_update_user_in_config(
    user_config: dict[str, Any], config_file: str
) -> bool:
    """Run ``update_user_in_config`` in the default thread executor.

    Args:
        user_config: Dictionary containing user configuration data.
        config_file: Path to the configuration file.

    Returns:
        Boolean result from the underlying synchronous function.
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
