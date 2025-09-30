"""BotManager implementation (moved from top-level bot_manager.py)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..application_context import ApplicationContext
from ..config.model import UserConfig
from ..constants import MANAGER_LOOP_SLEEP_SECONDS
from .core import TwitchColorBot
from .lifecycle_manager import BotLifecycleManager
from .signal_handler import SignalHandler


class BotManager:  # pylint: disable=too-many-instance-attributes
    """Manager for multiple TwitchColorBot instances.

    Handles creation, lifecycle management, and coordination of multiple bot instances.
    Provides restart functionality for configuration changes and graceful shutdown.
    Manages shared HTTP sessions.

    Attributes:
        users_config: List of user configuration dictionaries.
        config_file: Path to configuration file for persistence.
        bots: List of active TwitchColorBot instances.
        tasks: List of asyncio tasks for bot execution.
        running: Whether the manager is currently running.
        shutdown_initiated: Flag for shutdown initiation.
        restart_requested: Flag for restart request.
        new_config: New configuration for restart.
        context: Application context with shared services.
        http_session: Shared aiohttp ClientSession.
    """

    def __init__(
        self,
        users_config: list[dict[str, Any]],
        config_file: str | None = None,
        context: ApplicationContext | None = None,
    ) -> None:
        """Initialize the BotManager.

        Args:
            users_config: List of user configuration dictionaries.
            config_file: Path to configuration file for persistence.
            context: Application context with shared services.
        """
        self.lifecycle = BotLifecycleManager(users_config, config_file, context)
        self.signals = SignalHandler()

    # Delegate attributes to composed objects
    @property
    def users_config(self):
        return self.lifecycle.users_config

    @property
    def config_file(self):
        return self.lifecycle.config_file

    @property
    def bots(self):
        return self.lifecycle.bots

    @bots.setter
    def bots(self, value):
        self.lifecycle.bots = value

    @property
    def tasks(self):
        return self.lifecycle.tasks

    @tasks.setter
    def tasks(self, value):
        self.lifecycle.tasks = value

    @property
    def running(self):
        return self.lifecycle.running

    @running.setter
    def running(self, value: bool):
        self.lifecycle.running = value

    @property
    def shutdown_initiated(self):
        return self.signals.shutdown_initiated

    @shutdown_initiated.setter
    def shutdown_initiated(self, value: bool):
        self.signals.shutdown_initiated = value

    @property
    def restart_requested(self):
        return self.lifecycle.restart_requested

    @restart_requested.setter
    def restart_requested(self, value: bool):
        self.lifecycle.restart_requested = value

    @property
    def new_config(self):
        return self.lifecycle.new_config

    @new_config.setter
    def new_config(self, value):
        self.lifecycle.new_config = value

    @property
    def context(self):
        return self.lifecycle.context

    @property
    def http_session(self):
        return self.lifecycle.http_session

    @property
    def _manager_lock(self):
        return self.lifecycle._manager_lock

    # Delegate methods to composed objects
    async def _start_all_bots(self) -> bool:
        return await self.lifecycle._start_all_bots()

    def _create_bot(self, user_config: UserConfig) -> TwitchColorBot:
        return self.lifecycle._create_bot(user_config)

    async def _stop_all_bots(self) -> None:
        await self.lifecycle._stop_all_bots()

    def _cancel_all_tasks(self) -> None:
        self.lifecycle._cancel_all_tasks()

    def _close_all_bots(self) -> None:
        self.lifecycle._close_all_bots()

    async def _wait_for_task_completion(self) -> None:
        await self.lifecycle._wait_for_task_completion()

    def stop(self) -> None:
        self.signals.stop()

    async def _restart_with_new_config(self) -> bool:
        return await self.lifecycle._restart_with_new_config()

    def setup_signal_handlers(self) -> None:  # pragma: no cover
        self.signals.setup_signal_handlers()


async def _run_main_loop(manager: BotManager) -> None:
    """Run the main event loop for the bot manager.

    Monitors for shutdown/restart signals and handles bot task completion.

    Args:
        manager: The BotManager instance to monitor.
    """
    while manager.running:
        await asyncio.sleep(MANAGER_LOOP_SLEEP_SECONDS)
        if manager.shutdown_initiated:
            logging.warning("🔻 Shutdown initiated - stopping bots")
            async with manager._manager_lock:
                await manager._stop_all_bots()
            break
        if manager.restart_requested:
            ok = await manager._restart_with_new_config()
            if not ok:
                logging.error("⚠️ Restart failed - keeping previous config")
                continue
        if all(task.done() for task in manager.tasks):
            logging.warning("⚠️ All bot tasks completed unexpectedly")
            logging.info("⚠️ Likely authentication or connection issue")
            break


async def run_bots(
    users_config: list[dict[str, Any]], config_file: str | None = None
) -> None:
    """Run the bot application with the given configuration.

    Creates application context, initializes bot manager, starts bots,
    and handles shutdown gracefully.

    Args:
        users_config: List of user configuration dictionaries.
        config_file: Path to configuration file for persistence.

    Raises:
        asyncio.CancelledError: If operation is cancelled.
        RuntimeError: If bot startup fails.
        OSError: If system-level errors occur.
        ValueError: If configuration is invalid.
    """
    from ..application_context import ApplicationContext  # local import

    context = await ApplicationContext.create()
    await context.start()
    manager = BotManager(users_config, config_file, context=context)
    manager.setup_signal_handlers()
    try:
        async with manager._manager_lock:
            success = await manager._start_all_bots()
        if not success:
            return
        # Signal that all bots are launched and ready
        if context.cleanup_coordinator:
            await context.cleanup_coordinator.signal_bots_ready()
        logging.info("🏃 Bots running - press Ctrl+C to stop")
        await _run_main_loop(manager)
    except asyncio.CancelledError:
        logging.debug("Operation cancelled")
        raise
    except KeyboardInterrupt:  # noqa: PERF203
        logging.warning("⌨️ Keyboard interrupt")
    except (RuntimeError, OSError, ValueError) as e:
        logging.error(f"💥 Fatal error: {str(e)}")
    finally:
        await manager._stop_all_bots()
        logging.info("🔻 App initiating context shutdown")
        import asyncio as _asyncio

        try:
            await _asyncio.shield(context.shutdown())
        except (RuntimeError, OSError, ValueError):
            logging.warning("💥 Error during application context shutdown")
        logging.info("✅ App completed context shutdown")
        logging.info("👋 Goodbye")
