"""BotLifecycleManager - handles bot lifecycle operations."""

from __future__ import annotations

import asyncio
import logging
from secrets import SystemRandom
from typing import Any

import aiohttp

from ..application_context import ApplicationContext
from ..config.model import UserConfig
from ..constants import BOT_STARTUP_DELAY_SECONDS
from .core import TwitchColorBot

_jitter_rng = SystemRandom()


class BotLifecycleManager:  # pylint: disable=too-many-instance-attributes
    """Manager for bot lifecycle operations.

    Handles creation, starting, stopping, and restarting of bot instances.
    Manages shared HTTP sessions and task coordination.
    """

    tasks: list[asyncio.Task[Any]]

    def __init__(
        self,
        users_config: list[dict[str, Any]],
        config_file: str | None = None,
        context: ApplicationContext | None = None,
    ) -> None:
        """Initialize the BotLifecycleManager.

        Args:
            users_config: List of user configuration dictionaries.
            config_file: Path to configuration file for persistence.
            context: Application context with shared services.
        """
        # Convert dict configs to UserConfig dataclasses for type safety
        self.users_config = [UserConfig.from_dict(u) for u in users_config]
        self.config_file = config_file
        self.bots: list[TwitchColorBot] = []
        self.tasks: list[asyncio.Task[Any]] = []
        self.running = False
        self.restart_requested = False
        self.new_config: list[dict[str, Any]] | None = None
        self.context = context
        self.http_session: aiohttp.ClientSession | None = None
        self._manager_lock = asyncio.Lock()

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
            except (ValueError, RuntimeError, TypeError) as e:
                logging.error(
                    f"💥 Failed to create bot: {str(e)} user={user_config.username}"
                )
        if not self.bots:
            logging.error("⚠️ No bots created - aborting start")
            return False
        logging.debug(f"🚀 Launching bot tasks (count={len(self.bots)})")
        for bot in self.bots:
            self.tasks.append(asyncio.create_task(bot.start()))
        await asyncio.sleep(BOT_STARTUP_DELAY_SECONDS)
        self.running = True
        logging.debug("✅ All bots started successfully")
        return True

    def _create_bot(self, user_config: UserConfig) -> TwitchColorBot:
        """Create a TwitchColorBot instance from user configuration.

        Args:
            user_config: User configuration dataclass.

        Returns:
            Configured TwitchColorBot instance.
        """
        if not self.context or not self.context.session:
            raise RuntimeError("Context/session not initialized")
        username = user_config.username
        bot = TwitchColorBot(
            context=self.context,
            token=user_config.access_token or "",
            refresh_token=user_config.refresh_token or "",
            client_id=user_config.client_id or "",
            client_secret=user_config.client_secret or "",
            nick=username,
            channels=user_config.channels,
            http_session=self.context.session,
            is_prime_or_turbo=user_config.is_prime_or_turbo,
            config_file=self.config_file,
            user_id=None,
            enabled=user_config.enabled,
            token_expiry=user_config.token_expiry,
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
                    logging.debug(f"🛑 Cancelled task index={i}")
            except (ValueError, TypeError) as e:
                logging.warning(f"💥 Error cancelling task index={i}: {str(e)}")

    def _close_all_bots(self) -> None:
        """Close all bot instances."""
        for i, bot in enumerate(self.bots):
            try:
                bot.close()
                logging.info(f"🔻 Closed bot for user {bot.username}")
            except (OSError, ValueError, RuntimeError) as e:
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
        except (RuntimeError, ValueError, TypeError) as e:
            logging.warning(f"💥 Error waiting for task completion: {str(e)}")
        finally:
            self.tasks.clear()

    async def _restart_with_new_config(self) -> bool:
        """Restart all bots with the new configuration.

        Saves statistics, stops old bots, starts new ones, and restores statistics.

        Returns:
            True if restart successful, False otherwise.
        """
        async with self._manager_lock:
            if not self.new_config:
                return False
            logging.info("🔄 Restarting with new configuration")
            await self._stop_all_bots()
            self.bots.clear()
            self.tasks.clear()
            old_count = len(self.users_config)
            self.users_config = (
                [UserConfig.from_dict(u) for u in self.new_config]
                if self.new_config
                else []
            )
            new_count = len(self.users_config)
            logging.info(f"🛠️ Configuration updated old={old_count} new={new_count}")
            success = await self._start_all_bots()
            if success:
                try:
                    # Prune tokens for users no longer present
                    if self.context and self.context.token_manager:
                        active = {u.username.lower() for u in self.users_config}
                        await self.context.token_manager.prune(active)
                except (ValueError, RuntimeError) as e:
                    logging.debug(f"⚠️ Error pruning tokens: {str(e)}")
            self.restart_requested = False
            self.new_config = None
            return success
