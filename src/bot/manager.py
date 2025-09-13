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
    tasks: list[asyncio.Task[Any]]

    def __init__(
        self,
        users_config: list[dict[str, Any]],
        config_file: str | None = None,
        context: ApplicationContext | None = None,
    ) -> None:
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
        if not self.running:
            return
        logging.warning("🛑 Stopping all bots")
        self._cancel_all_tasks()
        self._close_all_bots()
        await self._wait_for_task_completion()
        self.running = False
        logging.info("🛑 All bots stopped")

    def _cancel_all_tasks(self) -> None:
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    logging.info(f"🛑 Cancelled task index={i}")
            except Exception as e:  # noqa: BLE001
                logging.warning(f"💥 Error cancelling task index={i}: {str(e)}")

    def _close_all_bots(self) -> None:
        for i, bot in enumerate(self.bots):
            try:
                bot.close()
                logging.info(f"🔻 Closed bot index={i} user={bot.username}")
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"💥 Error closing bot index={i}: {str(e)} user={getattr(bot, 'username', None)}"
                )

    async def _wait_for_task_completion(self) -> None:
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
        self.shutdown_initiated = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._stop_all_bots())
        except RuntimeError:
            pass

    def request_restart(self, new_users_config: list[dict[str, Any]]) -> None:
        logging.info("🔄 Config change detected - scheduling restart")
        self.new_config = new_users_config
        self.restart_requested = True

    async def _restart_with_new_config(self) -> bool:
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
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        return self._stats_service.save(bots_iter)

    def _restore_statistics(self, saved: dict[str, dict[str, int]]) -> None:
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        self._stats_service.restore(bots_iter, saved)

    def print_statistics(self) -> None:
        bots_iter: Iterable[_BotProto] = cast(Iterable["_BotProto"], self.bots)
        self._stats_service.aggregate(bots_iter)

    def setup_signal_handlers(self) -> None:  # pragma: no cover
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
