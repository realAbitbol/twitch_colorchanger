"""Health monitoring logic (moved from `manager_health.py`)."""

from __future__ import annotations

import asyncio
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any

from ..constants import HEALTH_MONITOR_INTERVAL
from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot
    from bot.manager import BotManager

_rng = SystemRandom()


class HealthMonitor:
    def __init__(self, manager: BotManager) -> None:
        self.manager = manager
        self._in_progress = False

    def start(self) -> asyncio.Task[Any]:
        return asyncio.create_task(self._loop())

    async def _loop(self) -> None:  # pragma: no cover (timing heavy)
        while self.manager.running and not self.manager.shutdown_initiated:
            try:
                jitter = _rng.uniform(0.8, 1.2)
                await asyncio.sleep(HEALTH_MONITOR_INTERVAL * jitter)
                if not self.manager.running or self.manager.shutdown_initiated:
                    break
                logger.log_event("manager", "health_tick", level=10)
                await self.perform_health_check()
            except asyncio.CancelledError:
                logger.log_event("manager", "health_cancelled", level=30)
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event("manager", "health_error", level=40, error=str(e))
                await asyncio.sleep(60 * _rng.uniform(0.5, 1.5))

    async def perform_health_check(self) -> None:
        if self._in_progress:
            logger.log_event("manager", "health_check_running", level=10)
            return
        self._in_progress = True
        try:
            unhealthy = self._identify_unhealthy_bots()
            if unhealthy:
                await self.manager._reconnect_unhealthy_bots(unhealthy)  # noqa: SLF001
            else:
                logger.log_event("manager", "all_healthy")
        finally:
            self._in_progress = False

    def _identify_unhealthy_bots(self) -> list[TwitchColorBot]:
        unhealthy: list[TwitchColorBot] = []
        for bot in self.manager.bots:
            try:
                if bot.irc and not bot.irc.is_healthy():
                    unhealthy.append(bot)
                    self._log_bot_health_issues(bot)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "health_error",
                    level=30,
                    error=str(e),
                    user=getattr(bot, "username", None),
                )
                unhealthy.append(bot)
        return unhealthy

    def _log_bot_health_issues(self, bot: TwitchColorBot) -> None:
        logger.log_event("manager", "bot_unhealthy", level=30, user=bot.username)
        if bot.irc:
            try:
                stats = bot.irc.get_connection_stats()
                logger.log_event(
                    "manager",
                    "bot_health_stats",
                    level=30,
                    user=bot.username,
                    time_since_activity=f"{stats['time_since_activity']:.1f}s",
                    connected=stats["connected"],
                    running=stats["running"],
                )
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager",
                    "connection_stats_error",
                    level=30,
                    user=bot.username,
                    error=str(e),
                )
        else:
            logger.log_event("manager", "irc_none", level=30, user=bot.username)
