import asyncio
import atexit

import aiohttp
import pytest

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
                except Exception:  # noqa: BLE001
                    pass
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


# Redundant safeguard in case process terminates before fixture finalizer
atexit.register(_close_all_sessions)
