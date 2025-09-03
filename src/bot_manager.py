"""Bot manager for handling multiple Twitch bots with structured logging."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from secrets import SystemRandom
from typing import Any

import aiohttp

from .application_context import ApplicationContext
from .bot import TwitchColorBot
from .config_watcher import create_config_watcher
from .constants import HEALTH_MONITOR_INTERVAL, TASK_WATCHDOG_INTERVAL
from .logger import logger
from .watcher_globals import set_global_watcher

_jitter_rng = SystemRandom()


class BotManager:  # pylint: disable=too-many-instance-attributes
    """Manages multiple Twitch bots (start/stop/health/restart)."""

    def __init__(
        self,
        users_config: list[dict[str, Any]],
        config_file: str | None = None,
        context: ApplicationContext | None = None,
    ):
        self.users_config = users_config
        self.config_file = config_file
        self.bots: list[TwitchColorBot] = []
        self.tasks: list[asyncio.Task] = []
        self.running = False
        self.shutdown_initiated = False
        self.restart_requested = False
        self.new_config: list[dict[str, Any]] | None = None
        self._health_check_in_progress = False
        self.context = context
        self.http_session: aiohttp.ClientSession | None = None

    # ---------------- Lifecycle -----------------
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

    async def _stop_all_bots(self):
        if not self.running:
            return
        logger.log_event("manager", "stopping_all", level=logging.WARNING)
        self._cancel_all_tasks()
        self._close_all_bots()
        # Session closed by ApplicationContext during global shutdown
        await self._wait_for_task_completion()
        self.running = False
        logger.log_event("manager", "all_stopped")

    def _cancel_all_tasks(self):
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

    def _close_all_bots(self):
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

    async def _wait_for_task_completion(self):
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

    # --------------- Public control ---------------
    def stop(self):
        self.shutdown_initiated = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._stop_all_bots())
        except RuntimeError:  # loop not running
            pass

    def request_restart(self, new_users_config: list[dict[str, Any]]):
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
        self.restart_requested = False
        self.new_config = None
        return success

    # --------------- Health monitoring ---------------
    async def _monitor_bot_health(self):
        while self.running and not self.shutdown_initiated:
            try:
                jitter = _jitter_rng.uniform(0.8, 1.2)
                await asyncio.sleep(HEALTH_MONITOR_INTERVAL * jitter)
                if not self.running or self.shutdown_initiated:
                    break
                logger.log_event("manager", "health_tick", level=logging.DEBUG)
                await self._perform_health_check()
            except asyncio.CancelledError:
                logger.log_event("manager", "health_cancelled", level=logging.WARNING)
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager", "health_error", level=logging.ERROR, error=str(e)
                )
                await asyncio.sleep(60 * _jitter_rng.uniform(0.5, 1.5))

    async def _perform_health_check(self):
        if self._health_check_in_progress:
            logger.log_event("manager", "health_check_running", level=logging.DEBUG)
            return
        self._health_check_in_progress = True
        try:
            unhealthy = self._identify_unhealthy_bots()
            if unhealthy:
                await self._reconnect_unhealthy_bots(unhealthy)
            else:
                logger.log_event("manager", "all_healthy")
        finally:
            self._health_check_in_progress = False

    async def _monitor_task_health(self):
        while self.running and not self.shutdown_initiated:
            try:
                jitter = _jitter_rng.uniform(0.7, 1.3)
                await asyncio.sleep(TASK_WATCHDOG_INTERVAL * jitter)
                if not self.running or self.shutdown_initiated:
                    break
                logger.log_event("manager", "task_watchdog_tick", level=logging.DEBUG)
                self._check_task_health()
            except asyncio.CancelledError:
                logger.log_event(
                    "manager", "task_watchdog_cancelled", level=logging.WARNING
                )
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager", "task_watchdog_error", level=logging.ERROR, error=str(e)
                )
                await asyncio.sleep(30)

    def _check_task_health(self):
        dead: list[int] = []
        alive: list[asyncio.Task] = []
        for i, task in enumerate(self.tasks):
            if task.done():
                if task.exception():
                    logger.log_event(
                        "manager",
                        "task_exception_detected",
                        level=logging.WARNING,
                        index=i,
                        error=str(task.exception()),
                    )
                else:
                    logger.log_event("manager", "task_completed", index=i)
                dead.append(i)
            else:
                alive.append(task)
        if dead:
            self.tasks = alive
            logger.log_event(
                "manager", "removed_dead_tasks", level=logging.WARNING, count=len(dead)
            )
        else:
            logger.log_event("manager", "all_tasks_alive", level=logging.DEBUG)

    def _identify_unhealthy_bots(self) -> list[TwitchColorBot]:
        unhealthy: list[TwitchColorBot] = []
        for bot in self.bots:
            try:
                if bot.irc and not bot.irc.is_healthy():
                    unhealthy.append(bot)
                    self._log_bot_health_issues(bot)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "health_error",
                    level=logging.WARNING,
                    error=str(e),
                    user=getattr(bot, "username", None),
                )
                unhealthy.append(bot)
        return unhealthy

    def _log_bot_health_issues(self, bot: TwitchColorBot):
        logger.log_event(
            "manager", "bot_unhealthy", level=logging.WARNING, user=bot.username
        )
        if bot.irc:
            try:
                stats = bot.irc.get_connection_stats()
                logger.log_event(
                    "manager",
                    "bot_health_stats",
                    level=logging.WARNING,
                    user=bot.username,
                    time_since_activity=f"{stats['time_since_activity']:.1f}s",
                    connected=stats["connected"],
                    running=stats["running"],
                )
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "connection_stats_error",
                    level=logging.WARNING,
                    user=bot.username,
                    error=str(e),
                )
        else:
            logger.log_event(
                "manager", "irc_none", level=logging.WARNING, user=bot.username
            )

    async def _reconnect_unhealthy_bots(self, bots: list[TwitchColorBot]):
        logger.log_event(
            "manager", "reconnecting_unhealthy", level=logging.WARNING, count=len(bots)
        )
        for bot in bots:
            success = await self._attempt_bot_reconnection(bot)
            if success:
                logger.log_event("manager", "reconnected_bot", user=bot.username)
            else:
                logger.log_event(
                    "manager",
                    "reconnect_failed",
                    level=logging.ERROR,
                    user=bot.username,
                )

    async def _attempt_bot_reconnection(self, bot: TwitchColorBot) -> bool:
        try:
            if not bot.irc:
                logger.log_event(
                    "manager",
                    "no_irc_for_reconnect",
                    level=logging.ERROR,
                    user=bot.username,
                )
                return False
            lock = self._get_bot_reconnect_lock(bot)
            async with lock:
                if self._bot_became_healthy(bot):
                    return True
                await self._cancel_stale_listener(bot)
                if not await self._force_bot_reconnect(bot):
                    return False
                if not self._start_fresh_listener(bot):
                    return False
                return await self._wait_for_health(bot)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager",
                "reconnect_error",
                level=logging.ERROR,
                user=bot.username,
                error=str(e),
            )
            return False

    def _get_bot_reconnect_lock(
        self, bot: TwitchColorBot
    ):  # pragma: no cover (simple helper)
        if not hasattr(bot, "_reconnect_lock"):
            import asyncio as _asyncio

            bot._reconnect_lock = _asyncio.Lock()  # type: ignore[attr-defined]
        return bot._reconnect_lock  # type: ignore[attr-defined]

    def _bot_became_healthy(self, bot: TwitchColorBot) -> bool:
        try:
            if bot.irc and bot.irc.is_healthy():
                logger.log_event(
                    "manager", "bot_healthy_before_reconnect", user=bot.username
                )
                return True
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager",
                "precheck_health_error",
                level=logging.WARNING,
                user=bot.username,
                error=str(e),
            )
        return False

    async def _cancel_stale_listener(self, bot: TwitchColorBot):
        if not hasattr(bot, "irc_task") or not bot.irc_task:  # type: ignore[attr-defined]
            return
        try:
            if not bot.irc_task.done():  # type: ignore[attr-defined]
                bot.irc_task.cancel()  # type: ignore[attr-defined]
                try:
                    await asyncio.wait_for(bot.irc_task, timeout=1.5)  # type: ignore[attr-defined]
                except (TimeoutError, asyncio.CancelledError):
                    pass
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager",
                "old_listener_cancel_error",
                level=logging.WARNING,
                user=bot.username,
                error=str(e),
            )

    async def _force_bot_reconnect(self, bot: TwitchColorBot) -> bool:
        if not bot.irc:
            logger.log_event(
                "manager",
                "no_irc_for_force_reconnect",
                level=logging.ERROR,
                user=bot.username,
            )
            return False
        success = await bot.irc.force_reconnect()
        if not success:
            logger.log_event(
                "manager",
                "irc_reconnect_failed",
                level=logging.ERROR,
                user=bot.username,
            )
            return False
        try:
            if getattr(bot, "irc_task", None) is not None and not bot.irc_task.done():  # type: ignore[attr-defined]
                bot.irc_task.cancel()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.log_event(
                "manager",
                "old_listener_cancel_noncritical",
                level=logging.DEBUG,
                user=bot.username,
            )
        if bot.irc:
            bot.irc_task = asyncio.create_task(bot.irc.listen())  # type: ignore[attr-defined]
        for channel in bot.irc.channels[1:] if bot.irc else []:
            try:
                if bot.irc:
                    await bot.irc.join_channel(channel)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "failed_rejoin_channel",
                    level=logging.WARNING,
                    user=bot.username,
                    channel=channel,
                    error=str(e),
                )
        return True

    def _start_fresh_listener(self, bot: TwitchColorBot) -> bool:
        try:
            if not bot.irc:
                logger.log_event(
                    "manager",
                    "cannot_start_listener",
                    level=logging.ERROR,
                    user=bot.username,
                )
                return False
            bot.irc_task = asyncio.create_task(bot.irc.listen())  # type: ignore[attr-defined]
            return True
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager",
                "listener_start_failed",
                level=logging.ERROR,
                user=bot.username,
                error=str(e),
            )
            return False

    async def _wait_for_health(self, bot: TwitchColorBot) -> bool:
        for _ in range(30):
            await asyncio.sleep(0.1)
            try:
                if bot.irc and bot.irc.is_healthy():
                    return True
            except Exception:  # noqa: BLE001
                break
        logger.log_event(
            "manager", "health_not_confirmed", level=logging.WARNING, user=bot.username
        )
        return False

    def _start_health_monitoring(self):
        if self.running:
            task = asyncio.create_task(self._monitor_bot_health())
            self.tasks.append(task)
            logger.log_event("manager", "started_health_monitor")

    def _start_task_watchdog(self):
        if self.running:
            task = asyncio.create_task(self._monitor_task_health())
            self.tasks.append(task)
            logger.log_event("manager", "started_task_watchdog")

    # --------------- Statistics ---------------
    def _save_statistics(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for bot in self.bots:
            stats[bot.username] = {
                "messages_sent": bot.messages_sent,
                "colors_changed": bot.colors_changed,
            }
        logger.log_event(
            "manager", "saved_statistics", level=logging.DEBUG, bots=len(stats)
        )
        return stats

    def _restore_statistics(self, saved: dict[str, dict[str, int]]):
        restored = 0
        for bot in self.bots:
            if bot.username in saved:
                bot.messages_sent = saved[bot.username]["messages_sent"]
                bot.colors_changed = saved[bot.username]["colors_changed"]
                restored += 1
        if restored:
            logger.log_event(
                "manager", "restored_statistics", level=logging.DEBUG, bots=restored
            )

    def print_statistics(self):  # keep method signature
        if not self.bots:
            return
        total_messages = sum(bot.messages_sent for bot in self.bots)
        total_colors = sum(bot.colors_changed for bot in self.bots)
        logger.log_event(
            "manager",
            "aggregate_statistics",
            bots=len(self.bots),
            total_messages=total_messages,
            total_color_changes=total_colors,
        )
        for bot in self.bots:
            bot.print_statistics()

    # --------------- Signals ---------------
    def setup_signal_handlers(self):  # pragma: no cover
        def handler(signum, _frame):  # noqa: D401
            logger.log_event(
                "manager", "signal_shutdown", level=logging.WARNING, signal=signum
            )
            self.shutdown_initiated = True
            _ = asyncio.create_task(self._stop_all_bots())

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


async def _setup_config_watcher(manager: BotManager, config_file: str | None):
    if not config_file or not os.path.exists(config_file):
        return None
    try:

        def restart_cb(new_config):
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


async def _run_main_loop(manager: BotManager):
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


def _cleanup_watcher(watcher):  # pragma: no cover
    if watcher:
        watcher.stop()
    try:
        set_global_watcher(None)
    except (ImportError, AttributeError):
        pass


async def run_bots(users_config: list[dict[str, Any]], config_file: str | None = None):
    from .application_context import ApplicationContext  # local import to avoid cycles

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
        from .logger import logger as _logger  # local import safe here

        _logger.log_event("app", "context_shutdown_begin")
        try:
            await context.shutdown()
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
