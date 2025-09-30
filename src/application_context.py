"""Central application context for shared async resources."""

from __future__ import annotations

import asyncio
import atexit
import logging

import aiohttp

from .auth_token.manager import TokenManager
from .config.async_persistence import cancel_pending_flush
from .utils.resource_monitor import get_resource_monitor, log_resource_usage

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
        """Create and initialize a new ApplicationContext instance.

        This factory method sets up the HTTP session and token manager,
        and registers the context globally for emergency cleanup.

        Returns:
            A fully initialized ApplicationContext instance.

        Raises:
            aiohttp.ClientError: If HTTP session creation fails.
            ValueError: If token manager initialization fails.
        """
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
        """Start the application context and its managed resources.

        This method ensures that the token manager is started if present,
        and marks the context as started. It is idempotent and thread-safe.

        Raises:
            Exception: If token manager startup fails.
        """
        async with self._lock:
            if self._started:
                return
            if self.token_manager:
                await self.token_manager.start()
            self._started = True
            logging.debug("🚀 Application context started")

            # Start resource monitoring for long-running applications
            try:
                resource_monitor = get_resource_monitor()
                await resource_monitor.start_monitoring()
                logging.debug("🔍 Resource monitoring started")
            except Exception as e:
                logging.warning(f"Failed to start resource monitoring: {e}")

    async def shutdown(self) -> None:
        """Shutdown the application context and clean up resources.

        This method stops the token manager, closes the HTTP session,
        and clears the global reference. It is thread-safe and ensures
        proper cleanup even if errors occur during shutdown.
        """
        async with self._lock:
            logging.info("🔻 Application context shutdown initiated")
            await self._stop_token_manager()
            await cancel_pending_flush()
            await self._close_http_session()

            # Stop resource monitoring
            try:
                resource_monitor = get_resource_monitor()
                await resource_monitor.stop_monitoring()
                log_resource_usage()  # Log final resource usage
                logging.debug("🔍 Resource monitoring stopped")
            except Exception as e:
                logging.warning(f"Failed to stop resource monitoring: {e}")

            self._started = False
            logging.info("✅ Application context shutdown complete")
            # After clean shutdown remove global reference so atexit won't re-run
            global GLOBAL_CONTEXT  # noqa: PLW0603
            if GLOBAL_CONTEXT is self:
                GLOBAL_CONTEXT = None

    async def _stop_token_manager(self) -> None:
        """Stop the token manager gracefully.

        Attempts to stop the token manager and handles any exceptions
        that may occur during shutdown, logging errors appropriately.
        """
        if not self.token_manager:
            return
        try:
            await self.token_manager.stop()
        except (RuntimeError, OSError, ValueError) as e:
            logging.error(f"💥 Error stopping token manager: {str(e)}")
        finally:
            self.token_manager = None


    async def _close_http_session(self) -> None:
        """Close the HTTP session gracefully.

        Attempts to close the aiohttp ClientSession and handles any
        exceptions that may occur, logging errors appropriately.
        """
        if not self.session:
            return
        try:
            await self.session.close()
        except (aiohttp.ClientError, OSError, ValueError) as e:
            logging.error(f"💥 Error closing HTTP session: {str(e)}")
        finally:
            self.session = None


# -------------------- Atexit Fallback (best-effort) -------------------- #
def _atexit_close() -> None:  # pragma: no cover - process teardown path
    """Emergency cleanup function registered with atexit.

    This function attempts to close any lingering HTTP session when the
    process exits abnormally. It safely handles event loop scenarios without
    creating new loops, and logs the outcome with robust error handling.
    """
    ctx = GLOBAL_CONTEXT
    if not ctx:
        return
    session = ctx.session
    if session and not session.closed:
        try:
            # Safely close session without creating new event loops
            # Try to get current loop first
            try:
                asyncio.get_running_loop()
                # If we have a running loop, we can't close the session here
                # Just log and hope normal shutdown handled it
                logging.debug("HTTP session cleanup skipped - event loop running")
            except RuntimeError:
                # No running loop, safe to close session
                # Use asyncio.run() which handles loop creation safely
                asyncio.run(_close_session_sync(session))
                logging.debug("HTTP session closed at exit")
        except Exception as e:
            # Final fallback - try to close without asyncio
            try:
                # For aiohttp sessions, we can try to close the underlying connector
                if hasattr(session, 'connector') and session.connector:
                    # This is a best-effort cleanup that doesn't require an event loop
                    logging.debug("Attempting direct session cleanup at exit")
            except Exception as cleanup_error:
                logging.debug(f"Direct session cleanup failed: {cleanup_error}")

            try:
                logging.warning(f"HTTP session close error at exit: {e}")
            except Exception:
                try:
                    import sys as _sys
                    _sys.stderr.write(f"[atexit] session close error: {e}\n")
                except Exception:  # noqa: S110
                    # Last resort error handling: if stderr write fails, silently ignore
                    pass  # pragma: no cover


async def _close_session_sync(session: aiohttp.ClientSession) -> None:
    """Safely close an aiohttp session.

    Args:
        session: The HTTP session to close.
    """
    try:
        await session.close()
    except Exception as e:
        logging.debug(f"Session close error during atexit: {e}")
        # Don't re-raise - this is cleanup code


atexit.register(_atexit_close)
