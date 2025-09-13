"""BotManager implementation (moved from top-level bot_manager.py)."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from ..application_context import ApplicationContext
from ..manager import ManagerStatistics

if TYPE_CHECKING:  # pragma: no cover
    from ..manager.statistics import _BotProto
from .core import TwitchColorBot

_jitter_rng = SystemRandom()


class BotManager:  # pylint: disable=too-many-instance-attributes
    """Manager for multiple TwitchColorBot instances.

    Handles creation, lifecycle management, and coordination of multiple bot instances.
    Provides restart functionality for configuration changes and graceful shutdown.
    Manages shared HTTP sessions and statistics aggregation across all bots.

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

    tasks: list[asyncio.Task[Any]]

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
        self.users_config = users_config
        self.config_file = config_file
        self.bots: list[TwitchColorBot] = []
        self.tasks: list[asyncio.Task[Any]] = []
        self.running = False
        self.shutdown_initiated = False
        self.restart_requested = False
        self.new_config: list[dict[str, Any]] | None = None
        self.context = context
        self.http_session: aiohttp.ClientSession | None = None
        self._stats_service = ManagerStatistics()

    async def _start_all_bots(self) -> bool:
        """Start all bots from the user configuration.

        Creates bot instances, launches their tasks, and sets running state.

        Returns:
            True if all bots started successfully, False otherwise.
        """
        logging.info(f"▶️ Starting all bots (count={len(self.users_config)})")
        if not self.context:
            raise RuntimeError("ApplicationContext required")
        self.http_session = self.context.session
        for user_config in self.users_config:
            try:
                bot = self._create_bot(user_config)
                self.bots.append(bot)
            except Exception as e:  # noqa: BLE001
                logging.error(
                    f"💥 Failed to create bot: {str(e)} user={user_config.get('username')}"
                )
        if not self.bots:
            logging.error("⚠️ No bots created - aborting start")
            return False
        logging.debug(f"🚀 Launching bot tasks (count={len(self.bots)})")
        for bot in self.bots:
            self.tasks.append(asyncio.create_task(bot.start()))
        await asyncio.sleep(1)
        self.running = True
        self.shutdown_initiated = False
        logging.debug("✅ All bots started successfully")
        return True

    def _create_bot(self, user_config: dict[str, Any]) -> TwitchColorBot:
        """Create a TwitchColorBot instance from user configuration.

        Args:
            user_config: User configuration dictionary.

        Returns:
            Configured TwitchColorBot instance.
        """
        if not self.context or not self.context.session:
            raise RuntimeError("Context/session not initialized")
        username = user_config["username"]
        bot = TwitchColorBot(
            context=self.context,
            token=user_config["access_token"],
            refresh_token=user_config.get("refresh_token", ""),
            client_id=user_config.get("client_id", ""),
            client_secret=user_config.get("client_secret", ""),
            nick=username,
            channels=user_config["channels"],
            http_session=self.context.session,
            is_prime_or_turbo=user_config.get("is_prime_or_turbo", True),
            config_file=self.config_file,
            user_id=None,
            enabled=user_config.get("enabled", True),
        )
        logging.debug(f"🆕 Bot created: {username}")
        return bot

    async def _stop_all_bots(self) -> None:
        """Stop all running bots and clean up resources."""
        if not self.running:
            return
        logging.warning("🛑 Stopping all bots")
        self._cancel_all_tasks()
        self._close_all_bots()
        await self._wait_for_task_completion()
        self.running = False
        logging.info("🛑 All bots stopped")

    def _cancel_all_tasks(self) -> None:
        """Cancel all running bot tasks."""
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    logging.info(f"🛑 Cancelled task index={i}")
            except Exception as e:  # noqa: BLE001
                logging.warning(f"💥 Error cancelling task index={i}: {str(e)}")

    def _close_all_bots(self) -> None:
        """Close all bot instances."""
        for i, bot in enumerate(self.bots):
            try:
                bot.close()
                logging.info(f"🔻 Closed bot index={i} user={bot.username}")
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"💥 Error closing bot index={i}: {str(e)} user={getattr(bot, 'username', None)}"
                )

    async def _wait_for_task_completion(self) -> None:
        """Wait for all bot tasks to complete and log any exceptions."""
        if not self.tasks:
            return
        try:
            results = await asyncio.gather(*self.tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.warning(
                        f"💥 Task index={i} finished with exception: {str(result)}"
                    )
        except Exception as e:  # noqa: BLE001
            logging.warning(f"💥 Error waiting for task completion: {str(e)}")
        finally:
            self.tasks.clear()

    def stop(self) -> None:
        """Initiate shutdown of all bots."""
        self.shutdown_initiated = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._stop_all_bots())
        except RuntimeError:
            pass

    def request_restart(self, new_users_config: list[dict[str, Any]]) -> None:
        """Request a restart with new user configuration.

        Args:
            new_users_config: New list of user configuration dictionaries.
        """
        logging.info("🔄 Config change detected - scheduling restart")
        self.new_config = new_users_config
        self.restart_requested = True

    async def _restart_with_new_config(self) -> bool:
        """Restart all bots with the new configuration.

        Saves statistics, stops old bots, starts new ones, and restores statistics.

        Returns:
            True if restart successful, False otherwise.
        """
        if not self.new_config:
            return False
        logging.info("🔄 Restarting with new configuration")
        saved = self._save_statistics()
        await self._stop_all_bots()
        self.bots.clear()
        self.tasks.clear()
        old_count = len(self.users_config)
        self.users_config = self.new_config
        new_count = len(self.users_config)
        logging.info(f"🛠️ Configuration updated old={old_count} new={new_count}")
        success = await self._start_all_bots()
        if success:
            self._restore_statistics(saved)
            try:
                # Prune tokens for users no longer present
                if self.context and self.context.token_manager:
                    active = {u.get("username", "").lower() for u in self.users_config}
                    self.context.token_manager.prune(active)
            except Exception as e:  # noqa: BLE001
                logging.debug(f"⚠️ Error pruning tokens: {str(e)}")
        self.restart_requested = False
        self.new_config = None
        return success

    def _save_statistics(self) -> dict[str, dict[str, int]]:
        """Save current bot statistics for restoration after restart.

        Returns:
            Dictionary of saved statistics.
        """
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        return self._stats_service.save(bots_iter)

    def _restore_statistics(self, saved: dict[str, dict[str, int]]) -> None:
        """Restore saved statistics to the new bot instances.

        Args:
            saved: Dictionary of saved statistics.
        """
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        self._stats_service.restore(bots_iter, saved)

    def print_statistics(self) -> None:
        """Print aggregated statistics for all bots."""
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        self._stats_service.aggregate(bots_iter)

    def setup_signal_handlers(self) -> None:  # pragma: no cover
        """Set up signal handlers for graceful shutdown on SIGINT/SIGTERM."""

        def handler(signum: int, _frame: object | None) -> None:  # noqa: D401
            # Idempotent signal handler: only trigger once
            if self.shutdown_initiated:
                return
            logging.warning(
                f"🛑 Signal received - initiating shutdown (signal={signum})"
            )
            self.shutdown_initiated = True
            # We don't directly stop bots here; main loop will detect flag and perform orderly shutdown

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


async def _run_main_loop(manager: BotManager) -> None:
    """Run the main event loop for the bot manager.

    Monitors for shutdown/restart signals and handles bot task completion.

    Args:
        manager: The BotManager instance to monitor.
    """
    while manager.running:
        await asyncio.sleep(1)
        if manager.shutdown_initiated:
            logging.warning("🔻 Shutdown initiated - stopping bots")
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
    """
    from ..application_context import ApplicationContext  # local import

    context = await ApplicationContext.create()
    await context.start()
    manager = BotManager(users_config, config_file, context=context)
    manager.setup_signal_handlers()
    try:
        success = await manager._start_all_bots()
        if not success:
            return
        logging.info("🏃 Bots running - press Ctrl+C to stop")
        await _run_main_loop(manager)
    except asyncio.CancelledError:
        logging.debug("Operation cancelled")
        raise
    except KeyboardInterrupt:  # noqa: PERF203
        logging.warning("⌨️ Keyboard interrupt")
    except Exception as e:  # noqa: BLE001
        logging.error(f"💥 Fatal error: {str(e)}")
    finally:
        await manager._stop_all_bots()
        logging.info("🔻 App initiating context shutdown")
        import asyncio as _asyncio

        try:
            await _asyncio.shield(context.shutdown())
        except Exception as e:  # noqa: BLE001
            if isinstance(e, asyncio.CancelledError):
                logging.debug("Shutdown cancelled (Ctrl+C)")
            else:
                logging.warning("💥 Error during application context shutdown")
        logging.info("✅ App completed context shutdown")
        manager.print_statistics()
        logging.info("👋 Goodbye")
