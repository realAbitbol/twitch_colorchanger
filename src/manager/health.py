"""Health monitoring logic (moved from `manager_health.py`)."""

from __future__ import annotations

import asyncio
import logging
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any

from ..constants import HEALTH_MONITOR_INTERVAL

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
                logging.debug("🕰️ Health check tick")
                await self.perform_health_check()
            except asyncio.CancelledError:
                logging.warning("🛑 Health monitoring cancelled")
                raise
            except Exception as e:  # noqa: BLE001
                logging.error(f"💥 Health monitor error: {str(e)}")
                await asyncio.sleep(60 * _rng.uniform(0.5, 1.5))

    async def perform_health_check(self) -> None:
        if self._in_progress:
            logging.debug("⏳ Health check already running - skip")
            return
        self._in_progress = True
        try:
            unhealthy = self._identify_unhealthy_bots()
            if unhealthy:
                await self.manager._reconnect_unhealthy_bots(unhealthy)  # noqa: SLF001
            else:
                logging.info("✅ All bots healthy")
        finally:
            self._in_progress = False

    def _identify_unhealthy_bots(self) -> list[TwitchColorBot]:
        unhealthy: list[TwitchColorBot] = []
        for bot in self.manager.bots:
            try:
                if bot.chat_backend and not bot.chat_backend.is_healthy():
                    unhealthy.append(bot)
                    self._log_bot_health_issues(bot)
            except Exception as e:  # noqa: BLE001
                logging.warning(f"💥 Health monitor error: {str(e)}")
                unhealthy.append(bot)
        return unhealthy

    def _log_bot_health_issues(self, bot: TwitchColorBot) -> None:
        logging.warning(f"❌ Bot unhealthy user={bot.username}")
        if bot.chat_backend:
            try:
                stats = bot.chat_backend.get_connection_stats()
                logging.warning(
                    "🩺 Bot health stats user={user} since={time_since_activity} connected={connected} running={running}".format(
                        user=bot.username,
                        time_since_activity=f"{stats['time_since_activity']:.1f}s",
                        connected=stats["connected"],
                        running=stats["running"],
                    )
                )
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"💥 Error getting connection stats for user={bot.username}: {str(e)}"
                )
        else:
            logging.warning(f"⚠️ No connection present user={bot.username}")
