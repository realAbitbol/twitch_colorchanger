"""CleanupCoordinator for managing centralized cleanup tasks.

This module provides the CleanupCoordinator singleton class that manages
cleanup tasks to ensure only one manager performs cleanup operations at a time.
It coordinates between multiple SubscriptionManager instances to prevent
concurrent stale subscription cleanup.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any


class CleanupCoordinator:
    """Singleton coordinator for cleanup tasks.

    This class ensures that only one cleanup task runs at a time across
    multiple managers, preventing conflicts and redundant operations.
    It uses a simple election mechanism where the first registered task
    becomes the active one.

    Attributes:
        _instance: Singleton instance.
        _active_cleanup_task: The currently active cleanup task.
        _registered_tasks: Set of registered cleanup tasks.
        _lock: Lock for thread-safe operations.
    """

    _instance: "CleanupCoordinator | None" = None
    _active_cleanup_task: asyncio.Task[Any] | None = None
    _registered_tasks: set[Callable[[], Coroutine[Any, Any, None]]] = set()
    _active_session_ids: set[str] = set()
    _lock: asyncio.Lock = asyncio.Lock()
    _bots_ready_event: asyncio.Event = asyncio.Event()

    def __new__(cls) -> "CleanupCoordinator":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the coordinator if not already done."""
        # Only initialize once due to singleton pattern
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._active_cleanup_task = None
            self._registered_tasks = set()
            self._active_session_ids = set()
            self._lock = asyncio.Lock()
            self._bots_ready_event = asyncio.Event()

    async def register_cleanup_task(
        self,
        cleanup_func: Callable[[], Coroutine[Any, Any, None]]
    ) -> bool:
        """Register a cleanup task with the coordinator.

        Only one task will be elected to run actively. Others will be
        registered but not executed. If no active task exists, this
        task becomes the active one.

        Args:
            cleanup_func: The cleanup function to register.

        Returns:
            bool: True if this task was elected as active, False otherwise.
        """
        async with self._lock:
            self._registered_tasks.add(cleanup_func)

            # If no active task, elect this one
            if self._active_cleanup_task is None or self._active_cleanup_task.done():
                self._active_cleanup_task = asyncio.create_task(self._run_cleanup_loop(cleanup_func))
                logging.info("🧹 CleanupCoordinator elected new active cleanup task")
                return True

            logging.debug("🧹 CleanupCoordinator registered passive cleanup task (already have active)")
            return False

    async def unregister_cleanup_task(
        self,
        cleanup_func: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Unregister a cleanup task.

        If this was the active task, a new one will be elected if available.

        Args:
            cleanup_func: The cleanup function to unregister.
        """
        async with self._lock:
            self._registered_tasks.discard(cleanup_func)

            # If this was the active task, cancel it and elect a new one if available
            if self._active_cleanup_task and not self._active_cleanup_task.done():
                # Cancel current task
                self._active_cleanup_task.cancel()
                try:
                    await self._active_cleanup_task
                except asyncio.CancelledError:
                    pass

                if len(self._registered_tasks) > 0:
                    # Elect new active task
                    new_func = next(iter(self._registered_tasks))
                    self._active_cleanup_task = asyncio.create_task(self._run_cleanup_loop(new_func))
                    logging.info("🧹 CleanupCoordinator elected new active cleanup task after unregistration")
                else:
                    # No more tasks, clear active task
                    self._active_cleanup_task = None

    async def register_session_id(self, session_id: str) -> None:
        """Register an active session ID.

        Args:
            session_id: The session ID to register.
        """
        async with self._lock:
            self._active_session_ids.add(session_id)
            logging.debug(f"🧹 Registered session ID: {session_id}")

    async def unregister_session_id(self, session_id: str) -> None:
        """Unregister a session ID.

        Args:
            session_id: The session ID to unregister.
        """
        async with self._lock:
            self._active_session_ids.discard(session_id)
            logging.debug(f"🧹 Unregistered session ID: {session_id}")

    def get_active_session_ids(self) -> list[str]:
        """Get list of all active session IDs.

        Returns:
            list[str]: List of active session IDs.
        """
        # No lock needed for reading since set operations are atomic
        return list(self._active_session_ids)

    async def signal_bots_ready(self) -> None:
        """Signal that all bots have been launched and are ready.

        This allows the cleanup loop to start running.
        """
        self._bots_ready_event.set()
        logging.info("🧹 CleanupCoordinator received bots ready signal")

    async def _run_cleanup_once(
        self,
        cleanup_func: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Run a single cleanup cycle if all managers have sessions.

        Args:
            cleanup_func: The cleanup function to run.
        """
        if len(self._registered_tasks) == len(self._active_session_ids):
            logging.info("🧹 Starting coordinated stale subscription cleanup")
            await cleanup_func()
            logging.info("✅ Coordinated stale subscription cleanup completed")
        else:
            logging.info(
                f"🧹 Skipping cleanup: {len(self._registered_tasks)} registered managers, "
                f"{len(self._active_session_ids)} active sessions"
            )

    async def _run_cleanup_loop(
        self,
        cleanup_func: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Run the cleanup loop for the active task.

        Args:
            cleanup_func: The cleanup function to run periodically.
        """
        await self._bots_ready_event.wait()
        logging.info("🧹 CleanupCoordinator bots ready signal received, starting cleanup loop")
        await asyncio.sleep(0.1)  # Allow all managers to complete registration
        interval = 6 * 3600  # 6 hours in seconds
        while True:
            try:
                async with self._lock:
                    await self._run_cleanup_once(cleanup_func)
            except Exception as e:
                logging.warning(f"⚠️ Error during coordinated cleanup: {str(e)}")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logging.debug("Coordinated cleanup loop cancelled")
                raise

    async def shutdown(self) -> None:
        """Shutdown the coordinator and cancel all tasks."""
        async with self._lock:
            if self._active_cleanup_task and not self._active_cleanup_task.done():
                self._active_cleanup_task.cancel()
                try:
                    await self._active_cleanup_task
                except asyncio.CancelledError:
                    pass
            self._active_cleanup_task = None
            self._registered_tasks.clear()
            self._active_session_ids.clear()
            logging.info("🧹 CleanupCoordinator shutdown complete")
