"""BotManager implementation (moved from top-level bot_manager.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Iterable
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from ..application_context import ApplicationContext
from ..config.globals import set_global_watcher
from ..config.watcher import create_config_watcher
from ..constants import (
    TASK_WATCHDOG_INTERVAL,  # noqa: F401 - may be used by watchdog service
)
from ..logs.logger import logger
from ..manager import HealthMonitor, ManagerStatistics

if TYPE_CHECKING:  # pragma: no cover
    from ..manager.statistics import _BotProto
from ..manager.task_watchdog import TaskWatchdog
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
        # Removed unused _health_check_in_progress (dead code)
        self.context = context
        self.http_session: aiohttp.ClientSession | None = None
        self._health_monitor: HealthMonitor | None = None
        self._task_watchdog: TaskWatchdog | None = None
        self._stats_service = ManagerStatistics()

    async def _start_all_bots(self) -> bool:
        logger.log_event("manager", "start_all", count=len(self.users_config))
        if not self.context:
            raise RuntimeError("ApplicationContext required")
        self.http_session = self.context.session
        for user_config in self.users_config:
            try:
                bot = self._create_bot(user_config)
                self.bots.append(bot)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "bot_create_failed",
                    level=logging.ERROR,
                    error=str(e),
                    user=user_config.get("username"),
                )
        if not self.bots:
            logger.log_event("manager", "no_bots", level=logging.ERROR)
            return False
        logger.log_event("manager", "launch_tasks", tasks=len(self.bots))
        for bot in self.bots:
            self.tasks.append(asyncio.create_task(bot.start()))
        await asyncio.sleep(1)
        self.running = True
        self.shutdown_initiated = False
        self._start_health_monitoring()
        self._start_task_watchdog()
        logger.log_event("manager", "all_started")
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
        logger.log_event("manager", "bot_created", user=username)
        return bot

    async def _stop_all_bots(self) -> None:
        if not self.running:
            return
        logger.log_event("manager", "stopping_all", level=logging.WARNING)
        self._cancel_all_tasks()
        self._close_all_bots()
        await self._wait_for_task_completion()
        self.running = False
        logger.log_event("manager", "all_stopped")

    def _cancel_all_tasks(self) -> None:
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    logger.log_event("manager", "task_cancelled", index=i)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "task_cancel_error",
                    level=logging.WARNING,
                    index=i,
                    error=str(e),
                )

    def _close_all_bots(self) -> None:
        for i, bot in enumerate(self.bots):
            try:
                bot.close()
                logger.log_event("manager", "bot_closed", index=i, user=bot.username)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "bot_close_error",
                    level=logging.WARNING,
                    index=i,
                    error=str(e),
                    user=getattr(bot, "username", None),
                )

    async def _wait_for_task_completion(self) -> None:
        if not self.tasks:
            return
        try:
            results = await asyncio.gather(*self.tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.log_event(
                        "manager",
                        "task_exception",
                        level=logging.WARNING,
                        index=i,
                        error=str(result),
                    )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager", "wait_tasks_error", level=logging.WARNING, error=str(e)
            )
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
        logger.log_event("manager", "config_change_detected")
        self.new_config = new_users_config
        self.restart_requested = True

    async def _restart_with_new_config(self) -> bool:
        if not self.new_config:
            return False
        logger.log_event("manager", "restarting")
        saved = self._save_statistics()
        await self._stop_all_bots()
        self.bots.clear()
        self.tasks.clear()
        old_count = len(self.users_config)
        self.users_config = self.new_config
        new_count = len(self.users_config)
        logger.log_event(
            "manager", "config_updated", old_users=old_count, new_users=new_count
        )
        success = await self._start_all_bots()
        if success:
            self._restore_statistics(saved)
            try:
                # Prune tokens for users no longer present
                if self.context and self.context.token_manager:
                    active = {u.get("username", "").lower() for u in self.users_config}
                    self.context.token_manager.prune(active)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager", "token_prune_failed", level=logging.DEBUG, error=str(e)
                )
        self.restart_requested = False
        self.new_config = None
        return success

    # Removed unused private monitoring coroutines (_monitor_bot_health,
    # _perform_health_check, _monitor_task_health) – monitoring handled by
    # HealthMonitor/TaskWatchdog services.

    def _check_task_health(self) -> None:
        if not self._task_watchdog:
            self._task_watchdog = TaskWatchdog(self)
        self._task_watchdog._check_task_health()  # noqa: SLF001

    def _start_health_monitoring(self) -> None:
        if self.running:
            if not self._health_monitor:
                self._health_monitor = HealthMonitor(self)
            task = self._health_monitor.start()
            self.tasks.append(task)
            logger.log_event("manager", "started_health_monitor")

    def _start_task_watchdog(self) -> None:
        if self.running:
            if not self._task_watchdog:
                self._task_watchdog = TaskWatchdog(self)
            task = self._task_watchdog.start()
            self.tasks.append(task)
            logger.log_event("manager", "started_task_watchdog")

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
            logger.log_event(
                "manager", "signal_shutdown", level=logging.WARNING, signal=signum
            )
            self.shutdown_initiated = True
            # We don't directly stop bots here; main loop will detect flag and perform orderly shutdown

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


async def _setup_config_watcher(manager: BotManager, config_file: str | None) -> Any:
    if not config_file or not os.path.exists(config_file):
        return None
    try:

        def restart_cb(new_config: list[dict[str, Any]]) -> None:
            manager.request_restart(new_config)

        watcher = await create_config_watcher(config_file, restart_cb)
        set_global_watcher(watcher)
        logger.log_event("manager", "config_watcher_enabled", file=config_file)
        return watcher
    except ImportError:
        logger.log_event(
            "manager", "config_watching_unavailable", level=logging.WARNING
        )
        return None
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "manager",
            "config_watcher_start_failed",
            level=logging.WARNING,
            error=str(e),
        )
        return None


async def _run_main_loop(manager: BotManager) -> None:
    while manager.running:
        await asyncio.sleep(1)
        if manager.shutdown_initiated:
            logger.log_event("manager", "shutdown_initiated", level=logging.WARNING)
            await manager._stop_all_bots()
            break
        if manager.restart_requested:
            ok = await manager._restart_with_new_config()
            if not ok:
                logger.log_event(
                    "manager", "restart_failed_keep_previous", level=logging.ERROR
                )
            continue
        if all(task.done() for task in manager.tasks):
            logger.log_event(
                "manager", "all_tasks_completed_unexpectedly", level=logging.WARNING
            )
            logger.log_event("manager", "possible_auth_issue")
            break


def _cleanup_watcher(watcher: Any) -> None:  # pragma: no cover
    if watcher:
        watcher.stop()
    try:
        set_global_watcher(None)
    except (ImportError, AttributeError):
        pass


async def run_bots(
    users_config: list[dict[str, Any]], config_file: str | None = None
) -> None:
    from ..application_context import ApplicationContext  # local import

    context = await ApplicationContext.create()
    await context.start()
    manager = BotManager(users_config, config_file, context=context)
    manager.setup_signal_handlers()
    watcher = await _setup_config_watcher(manager, config_file)
    try:
        success = await manager._start_all_bots()
        if not success:
            return
        logger.log_event("manager", "bots_running")
        await _run_main_loop(manager)
    except KeyboardInterrupt:  # noqa: PERF203
        logger.log_event("manager", "keyboard_interrupt", level=logging.WARNING)
    except Exception as e:  # noqa: BLE001
        logger.log_event("manager", "fatal_error", level=logging.ERROR, error=str(e))
    finally:
        _cleanup_watcher(watcher)
        await manager._stop_all_bots()
        from ..logs.logger import logger as _logger  # local to avoid cycles

        _logger.log_event("app", "context_shutdown_begin")
        import asyncio as _asyncio

        try:
            await _asyncio.shield(context.shutdown())
        except Exception as e:  # noqa: BLE001
            if isinstance(e, asyncio.CancelledError):
                _logger.log_event(
                    "context",
                    "shutdown_cancelled",
                    level=logging.DEBUG,
                    human="Shutdown cancelled (Ctrl+C)",
                )
            else:
                _logger.log_event(
                    "context", "shutdown_error", level=logging.WARNING, error=str(e)
                )
        _logger.log_event("app", "context_shutdown_complete")
        manager.print_statistics()
        logger.log_event("manager", "goodbye")
