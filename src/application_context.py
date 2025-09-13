"""Central application context for shared async resources."""

from __future__ import annotations

import asyncio
import atexit
import logging

import aiohttp

from .auth_token.manager import TokenManager

# Global reference for emergency cleanup if normal shutdown is interrupted
GLOBAL_CONTEXT: ApplicationContext | None = None


class ApplicationContext:
    """Holds shared async resources for the application lifecycle."""

    # Class / instance attribute type declarations (helps mypy)
    session: aiohttp.ClientSession | None
    token_manager: TokenManager | None
    _started: bool
    _lock: asyncio.Lock

    def __init__(self) -> None:
        # Core resources
        self.session = None
        self.token_manager = None
        # Lifecycle flags
        self._started = False
        self._lock = asyncio.Lock()

    # ------------------------- Construction ------------------------- #
    @classmethod
    async def create(cls) -> ApplicationContext:
        ctx = cls()
        logging.debug("🧪 Creating application context")
        ctx.session = aiohttp.ClientSession()
        logging.debug("🔗 HTTP session created")
        ctx.token_manager = TokenManager(ctx.session)
        # Register globally for atexit fallback
        global GLOBAL_CONTEXT  # noqa: PLW0603
        GLOBAL_CONTEXT = ctx
        return ctx

    # --------------------------- Lifecycle -------------------------- #
    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            if self.token_manager:
                await self.token_manager.start()
            self._started = True
            logging.debug("🚀 Application context started")

    async def shutdown(self) -> None:
        async with self._lock:
            logging.info("🔻 Application context shutdown initiated")
            await self._stop_token_manager()
            await self._close_http_session()
            self._started = False
            logging.info("✅ Application context shutdown complete")
            # After clean shutdown remove global reference so atexit won't re-run
            global GLOBAL_CONTEXT  # noqa: PLW0603
            if GLOBAL_CONTEXT is self:
                GLOBAL_CONTEXT = None

    async def _stop_token_manager(self) -> None:
        if not self.token_manager:
            return
        try:
            await self.token_manager.stop()
        except Exception as e:  # noqa: BLE001
            if isinstance(e, asyncio.CancelledError):
                logging.warning("🛑 Token manager cancellation during shutdown")
            else:
                logging.error(f"💥 Error stopping token manager: {str(e)}")
        finally:
            self.token_manager = None

    async def _close_http_session(self) -> None:
        if not self.session:
            return
        try:
            await self.session.close()
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 Error closing HTTP session: {str(e)}")
        finally:
            self.session = None


# -------------------- Atexit Fallback (best-effort) -------------------- #
def _atexit_close() -> None:  # pragma: no cover - process teardown path
    ctx = GLOBAL_CONTEXT
    if not ctx:
        return
    session = ctx.session
    if session and not session.closed:
        try:
            # Create a temporary loop just to close the session cleanly
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(session.close())
            finally:
                loop.close()
            logging.info("HTTP session closed at exit")
        except Exception as e:  # noqa: BLE001
            try:
                logging.warning(f"HTTP session close error at exit: {e}")
            except Exception:
                try:
                    import sys as _sys

                    _sys.stderr.write(f"[atexit] session close error: {e}\n")
                except Exception:  # noqa: S110
                    # Last resort error handling: if stderr write fails, silently ignore as nothing more can be done
                    pass  # pragma: no cover  # nosec B110


atexit.register(_atexit_close)
