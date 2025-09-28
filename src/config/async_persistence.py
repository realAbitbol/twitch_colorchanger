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
import os
import shutil
import time
from contextlib import suppress
from typing import Any

from ..constants import (
    CONFIG_DEBOUNCE_SECONDS,
    CONFIG_MAX_FAILURES_WARNING,
)
from .core import update_user_in_config

__all__ = [
    "async_update_user_in_config",
    "cancel_pending_flush",
    "flush_pending_updates",
    "queue_user_update",
]

# --- Debounced batching infrastructure ---

_PENDING: dict[str, tuple[dict[str, Any], float]] = {}
_FLUSH_TASK: asyncio.Task[Any] | None = None
_LOCK = asyncio.Lock()
_DEBOUNCE_SECONDS = CONFIG_DEBOUNCE_SECONDS  # adjustable small delay to coalesce bursts
_USER_LOCK_TTL_SECONDS = 300  # 5 minutes TTL for user lock registry entries

# Single lock for all persistence operations to prevent interleaving.
_PERSISTENCE_LOCK = asyncio.Lock()


async def _flush(config_file: str) -> None:
    """Flush pending user updates to the config file.

    Args:
        config_file: Path to the configuration file.
    """
    global _FLUSH_TASK
    async with _LOCK:
        now = time.time()
        pending = [config for config, ts in _PENDING.values() if now - ts <= _USER_LOCK_TTL_SECONDS]
        _PENDING.clear()
        _FLUSH_TASK = None
    if not pending:
        return
    _log_batch_start(len(pending))
    failures = await _persist_batch(pending, config_file)
    _log_batch_result(failures, len(pending))


def _log_batch_start(count: int) -> None:
    """Log the start of a batch flush operation.

    Args:
        count: Number of pending updates.
    """
    with suppress(Exception):
        logging.debug(
            f"📤 Config batch flush count={count} debounce_seconds={_DEBOUNCE_SECONDS}"
        )


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
    if not pending:
        return 0

    backup_file = f"{config_file}.backup"
    try:
        shutil.copy2(config_file, backup_file)
    except Exception as e:
        logging.error(f"Failed to create backup for batch persistence: {e}")
        return len(pending)  # fail all if can't backup

    failures = 0
    for uc in pending:
        uname = str(uc.get("username", "")).lower()
        try:
            loop = asyncio.get_event_loop()
            async with _PERSISTENCE_LOCK:
                success = await loop.run_in_executor(
                    None, update_user_in_config, uc, config_file
                )
            if not success:
                failures += 1
        except Exception as e:  # noqa: BLE001
            failures += 1
            if failures <= CONFIG_MAX_FAILURES_WARNING:
                logging.warning(
                    f"⚠️ Error writing batch item user={uname or uc.get('username')}: {str(e)}"
                )

    if failures > 0:
        try:
            shutil.copy2(backup_file, config_file)
        except Exception as e:
            logging.error(f"Failed to rollback batch: {e}")

    try:
        os.remove(backup_file)
    except Exception as e:
        logging.warning(f"Failed to remove backup file: {e}")

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
        now = time.time()
        # Clean expired entries
        expired = [k for k, (_, ts) in _PENDING.items() if now - ts > _USER_LOCK_TTL_SECONDS]
        for k in expired:
            del _PENDING[k]
        # Update or add entry
        existing_config, _ = _PENDING.get(uname, ({}, 0))
        merged = {**existing_config, **user_config}
        _PENDING[uname] = (merged, now)
        global _FLUSH_TASK
        if _FLUSH_TASK is None or _FLUSH_TASK.done():
            _FLUSH_TASK = asyncio.create_task(_schedule_flush(config_file))


async def cancel_pending_flush() -> None:
    """Cancel any pending flush task to prevent warnings on shutdown."""
    async with _LOCK:
        global _FLUSH_TASK
        if _FLUSH_TASK and not _FLUSH_TASK.done():
            logging.debug("Cancelling pending flush task")
            _FLUSH_TASK.cancel()
            try:
                await _FLUSH_TASK
            except asyncio.CancelledError:  # noqa
                pass
            _FLUSH_TASK = None


async def flush_pending_updates(config_file: str) -> None:
    """Force an immediate flush (e.g., before shutdown).

    Args:
        config_file: Path to the configuration file.
    """
    await cancel_pending_flush()
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
    async with _PERSISTENCE_LOCK:
        return await loop.run_in_executor(
            None, update_user_in_config, user_config, config_file
        )
