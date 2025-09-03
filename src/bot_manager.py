"""Bot manager for handling multiple Twitch bots with structured logging."""

from __future__ import annotations

import asyncio
import os
import signal
from secrets import SystemRandom
from typing import Any

import aiohttp

from .bot import TwitchColorBot
from .config_watcher import create_config_watcher
from .constants import HEALTH_MONITOR_INTERVAL, TASK_WATCHDOG_INTERVAL
from .logger import logger
from .watcher_globals import set_global_watcher

_jitter_rng = SystemRandom()  # Non-crypto jitter rng


class BotManager:  # pylint: disable=too-many-instance-attributes
    """Manages multiple Twitch bots (start/stop/health/restart)."""

    def __init__(
        self, users_config: list[dict[str, Any]], config_file: str | None = None
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
        self.http_session: aiohttp.ClientSession | None = None

    # ---------------- Lifecycle -----------------
    async def _start_all_bots(self) -> bool:
        logger.info("Starting bots", count=len(self.users_config))
        logger.info("Creating shared HTTP session")
        self.http_session = aiohttp.ClientSession()

        for user_config in self.users_config:
            try:
                bot = self._create_bot(user_config)
                self.bots.append(bot)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"Failed to create bot: {e}",
                    user=user_config.get("username"),
                )

        if not self.bots:
            logger.error("No bots created - aborting start")
            return False

        logger.info("Launching bot tasks", tasks=len(self.bots))
        for bot in self.bots:
            self.tasks.append(asyncio.create_task(bot.start()))

        await asyncio.sleep(1)  # allow initialization
        self.running = True
        self.shutdown_initiated = False
        self._start_health_monitoring()
        self._start_task_watchdog()
        logger.info("All bots started successfully")
        return True

    def _create_bot(self, user_config: dict[str, Any]) -> TwitchColorBot:
        if not self.http_session:
            raise RuntimeError("HTTP session not initialized")
        username = user_config["username"]
        bot = TwitchColorBot(
            token=user_config["access_token"],
            refresh_token=user_config.get("refresh_token", ""),
            client_id=user_config.get("client_id", ""),
            client_secret=user_config.get("client_secret", ""),
            nick=username,
            channels=user_config["channels"],
            http_session=self.http_session,
            is_prime_or_turbo=user_config.get("is_prime_or_turbo", True),
            config_file=self.config_file,
            user_id=None,
        )
        logger.info("Bot created", user=username)
        return bot

    async def _stop_all_bots(self):
        if not self.running:
            return
        logger.warning("Stopping all bots")
        self._cancel_all_tasks()
        self._close_all_bots()
        if self.http_session:
            try:
                await self.http_session.close()
            finally:
                self.http_session = None
        await self._wait_for_task_completion()
        self.running = False
        logger.info("All bots stopped")

    def _cancel_all_tasks(self):
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    logger.info("Cancelled task", index=i)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error cancelling task {i}: {e}")

    def _close_all_bots(self):
        for i, bot in enumerate(self.bots):
            try:
                bot.close()
                logger.info("Closed bot", index=i, user=bot.username)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Error closing bot {i}: {e}", user=getattr(bot, "username", None)
                )

    async def _wait_for_task_completion(self):
        if not self.tasks:
            return
        try:
            results = await asyncio.gather(*self.tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"Task {i} finished with exception: {result}", index=i
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error waiting for task completion: {e}")
        finally:
            self.tasks.clear()

    # --------------- Public control ---------------
    def stop(self):
        self.shutdown_initiated = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._stop_all_bots())
        except RuntimeError:
            pass

    def request_restart(self, new_users_config: list[dict[str, Any]]):
        logger.info("Config change detected - scheduling restart")
        self.new_config = new_users_config
        self.restart_requested = True

    async def _restart_with_new_config(self) -> bool:
        if not self.new_config:
            return False
        logger.info("Restarting with new configuration")
        saved = self._save_statistics()
        await self._stop_all_bots()
        self.bots.clear()
        self.tasks.clear()
        old_count = len(self.users_config)
        self.users_config = self.new_config
        new_count = len(self.users_config)
        logger.info("Config updated", old_users=old_count, new_users=new_count)
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
                logger.debug("Health check tick")
                await self._perform_health_check()
            except asyncio.CancelledError:
                logger.warning("Health monitoring cancelled")
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(60 * _jitter_rng.uniform(0.5, 1.5))

    async def _perform_health_check(self):
        if self._health_check_in_progress:
            logger.debug("Health check already running - skip")
            return
        self._health_check_in_progress = True
        try:
            unhealthy = self._identify_unhealthy_bots()
            if unhealthy:
                await self._reconnect_unhealthy_bots(unhealthy)
            else:
                logger.info("All bots healthy")
        finally:
            self._health_check_in_progress = False

    async def _monitor_task_health(self):
        while self.running and not self.shutdown_initiated:
            try:
                jitter = _jitter_rng.uniform(0.7, 1.3)
                await asyncio.sleep(TASK_WATCHDOG_INTERVAL * jitter)
                if not self.running or self.shutdown_initiated:
                    break
                logger.debug("Task watchdog tick")
                self._check_task_health()
            except asyncio.CancelledError:
                logger.warning("Task watchdog cancelled")
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"Task watchdog error: {e}")
                await asyncio.sleep(30)

    def _check_task_health(self):
        dead = []
        alive = []
        for i, task in enumerate(self.tasks):
            if task.done():
                if task.exception():
                    logger.warning(f"Task {i} exception: {task.exception()}", index=i)
                else:
                    logger.info("Task completed", index=i)
                dead.append(i)
            else:
                alive.append(task)
        if dead:
            self.tasks = alive
            logger.warning("Removed dead tasks", count=len(dead))
        else:
            logger.debug("All tasks alive")

    def _identify_unhealthy_bots(self) -> list[TwitchColorBot]:
        unhealthy: list[TwitchColorBot] = []
        for bot in self.bots:
            try:
                if bot.irc and not bot.irc.is_healthy():
                    unhealthy.append(bot)
                    self._log_bot_health_issues(bot)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Health check error for bot: {e}",
                    user=getattr(bot, "username", None),
                )
                unhealthy.append(bot)
        return unhealthy

    def _log_bot_health_issues(self, bot: TwitchColorBot):
        logger.warning("Bot unhealthy", user=bot.username)
        if bot.irc:
            try:
                stats = bot.irc.get_connection_stats()
                logger.warning(
                    "Bot health stats",
                    user=bot.username,
                    time_since_activity=f"{stats['time_since_activity']:.1f}s",
                    connected=stats["connected"],
                    running=stats["running"],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Error getting connection stats: {e}", user=bot.username
                )
        else:
            logger.warning("IRC connection is None", user=bot.username)

    async def _reconnect_unhealthy_bots(self, bots: list[TwitchColorBot]):
        logger.warning("Reconnecting unhealthy bots", count=len(bots))
        for bot in bots:
            success = await self._attempt_bot_reconnection(bot)
            if success:
                logger.info("Reconnected bot", user=bot.username)
            else:
                logger.error("Failed to reconnect bot", user=bot.username)

    async def _attempt_bot_reconnection(self, bot: TwitchColorBot) -> bool:
        try:
            if not bot.irc:
                logger.error("No IRC connection to reconnect", user=bot.username)
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
            logger.error(f"Reconnection error: {e}", user=bot.username)
            return False

    def _get_bot_reconnect_lock(self, bot: TwitchColorBot):
        if not hasattr(bot, "_reconnect_lock"):
            import asyncio as _asyncio

            bot._reconnect_lock = _asyncio.Lock()  # type: ignore[attr-defined]
        return bot._reconnect_lock  # type: ignore[attr-defined]

    def _bot_became_healthy(self, bot: TwitchColorBot) -> bool:
        try:
            if bot.irc and bot.irc.is_healthy():
                logger.info("Bot became healthy before reconnect", user=bot.username)
                return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Pre-check health error: {e}", user=bot.username)
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
            logger.warning(f"Error cancelling old listener: {e}", user=bot.username)

    async def _force_bot_reconnect(self, bot: TwitchColorBot) -> bool:
        if not bot.irc:
            logger.error("No IRC instance present for reconnect", user=bot.username)
            return False
        success = await bot.irc.force_reconnect()
        if not success:
            logger.error("IRC reconnection failed", user=bot.username)
            return False
        try:
            if getattr(bot, "irc_task", None) is not None and not bot.irc_task.done():  # type: ignore[attr-defined]
                bot.irc_task.cancel()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.debug(
                "Old listener cancellation raised non-critical exception",
                user=bot.username,
            )
        if bot.irc:
            bot.irc_task = asyncio.create_task(bot.irc.listen())  # type: ignore[attr-defined]
        for channel in bot.irc.channels[1:] if bot.irc else []:
            try:
                if bot.irc:
                    await bot.irc.join_channel(channel)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Failed rejoin channel: {e}", user=bot.username, channel=channel
                )
        return True

    def _start_fresh_listener(self, bot: TwitchColorBot) -> bool:
        try:
            if not bot.irc:
                logger.error(
                    "Cannot start listener without IRC instance", user=bot.username
                )
                return False
            bot.irc_task = asyncio.create_task(bot.irc.listen())  # type: ignore[attr-defined]
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Listener start failed: {e}", user=bot.username)
            return False

    async def _wait_for_health(self, bot: TwitchColorBot) -> bool:
        for _ in range(30):  # ~3s
            await asyncio.sleep(0.1)
            try:
                if bot.irc and bot.irc.is_healthy():
                    return True
            except Exception:  # noqa: BLE001
                break
        logger.warning("Health not confirmed after reconnect", user=bot.username)
        return False

    def _start_health_monitoring(self):
        if self.running:
            task = asyncio.create_task(self._monitor_bot_health())
            self.tasks.append(task)
            logger.info("Started health monitor")

    def _start_task_watchdog(self):
        if self.running:
            task = asyncio.create_task(self._monitor_task_health())
            self.tasks.append(task)
            logger.info("Started task watchdog")

    # --------------- Statistics ---------------
    def _save_statistics(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for bot in self.bots:
            stats[bot.username] = {
                "messages_sent": bot.messages_sent,
                "colors_changed": bot.colors_changed,
            }
        logger.debug("Saved statistics", bots=len(stats))
        return stats

    def _restore_statistics(self, saved: dict[str, dict[str, int]]):
        restored = 0
        for bot in self.bots:
            if bot.username in saved:
                bot.messages_sent = saved[bot.username]["messages_sent"]
                bot.colors_changed = saved[bot.username]["colors_changed"]
                restored += 1
        if restored:
            logger.debug("Restored statistics", bots=restored)

    def print_statistics(self):  # keep method signature (used externally)
        if not self.bots:
            return
        total_messages = sum(bot.messages_sent for bot in self.bots)
        total_colors = sum(bot.colors_changed for bot in self.bots)
        logger.info(
            "Aggregate statistics",
            bots=len(self.bots),
            total_messages=total_messages,
            total_color_changes=total_colors,
        )
        for bot in self.bots:
            bot.print_statistics()

    # --------------- Signals ---------------
    def setup_signal_handlers(self):  # pragma: no cover - system interaction
        def handler(signum, _frame):  # noqa: D401
            logger.warning("Signal received - initiating shutdown", signal=signum)
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
        logger.info("Config watcher enabled", file=config_file)
        return watcher
    except ImportError:
        logger.warning("Config watching unavailable - install watchdog")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Config watcher start failed: {e}")
        return None


async def _run_main_loop(manager: BotManager):
    while manager.running:
        await asyncio.sleep(1)
        if manager.shutdown_initiated:
            logger.warning("Shutdown initiated - stopping bots")
            await manager._stop_all_bots()
            break
        if manager.restart_requested:
            ok = await manager._restart_with_new_config()
            if not ok:
                logger.error("Restart failed - keeping previous config")
            continue
        if all(task.done() for task in manager.tasks):
            logger.warning("All bot tasks completed unexpectedly")
            logger.info("Likely authentication or connection issue")
            break


def _cleanup_watcher(watcher):  # pragma: no cover
    if watcher:
        watcher.stop()
    try:
        set_global_watcher(None)
    except (ImportError, AttributeError):
        pass


async def run_bots(users_config: list[dict[str, Any]], config_file: str | None = None):
    manager = BotManager(users_config, config_file)
    manager.setup_signal_handlers()
    watcher = await _setup_config_watcher(manager, config_file)
    try:
        success = await manager._start_all_bots()
        if not success:
            return
        logger.info("Bots running - press Ctrl+C to stop")
        await _run_main_loop(manager)
    except KeyboardInterrupt:  # noqa: PERF203
        logger.warning("Keyboard interrupt")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Fatal error: {e}")
    finally:
        _cleanup_watcher(watcher)
        await manager._stop_all_bots()
        manager.print_statistics()
        logger.info("Goodbye")
