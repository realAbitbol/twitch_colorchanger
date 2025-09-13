import asyncio
import atexit
import logging

import aiohttp
import pytest
import pytest_asyncio

# Track created aiohttp.ClientSession objects so we can close them at the end
_CREATED_SESSIONS: set[aiohttp.ClientSession] = set()

_original_init = aiohttp.ClientSession.__init__  # type: ignore[attr-defined]


def _tracking_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    _original_init(self, *args, **kwargs)
    _CREATED_SESSIONS.add(self)


aiohttp.ClientSession.__init__ = _tracking_init  # type: ignore[assignment]


def _close_all_sessions() -> None:
    async def _close():
        for sess in _CREATED_SESSIONS:
            if not sess.closed:
                try:
                    await sess.close()
                except Exception as e:  # noqa: BLE001
                    logging.warning(f"Error closing session: {str(e)}")
    try:
        asyncio.run(_close())
    except RuntimeError:
        # Event loop already running / closed; best effort fallback
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_close())
        finally:
            loop.close()


@pytest.fixture(scope="session", autouse=True)
def _session_cleanup():  # type: ignore[coverage]
    yield
    _close_all_sessions()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _async_persistence_teardown():
    """Teardown fixture to reset async_persistence module state between tests.

    This ensures no lingering background tasks, pending updates, or locks
    from previous tests affect subsequent test runs. Addresses async/infrastructure
    issues by properly cleaning up:
    - Background flush tasks (_FLUSH_TASK)
    - Pending update queues (_PENDING)
    - Per-user locks (_USER_LOCKS)
    """
    from src.config.async_persistence import (
        _FLUSH_TASK,
        _LOCK,
        _PENDING,
        _USER_LOCKS,
        _USER_LOCKS_LOCK,
    )

    yield

    # Cancel any running flush task to prevent lingering background operations
    if _FLUSH_TASK and not _FLUSH_TASK.done():
        _FLUSH_TASK.cancel()
        try:
            await _FLUSH_TASK
        except asyncio.CancelledError:
            # Clear pending updates to reset state for next test
            async with _LOCK:
                _PENDING.clear()

            # Clear user locks to prevent lock pollution between tests
            async with _USER_LOCKS_LOCK:
                _USER_LOCKS.clear()
            raise

    # Clear pending updates to reset state for next test
    async with _LOCK:
        _PENDING.clear()

    # Clear user locks to prevent lock pollution between tests
    async with _USER_LOCKS_LOCK:
        _USER_LOCKS.clear()


# Redundant safeguard in case process terminates before fixture finalizer
atexit.register(_close_all_sessions)
