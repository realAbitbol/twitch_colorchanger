"""Task watchdog extracted from BotManager to isolate task supervision."""

from __future__ import annotations

import asyncio
import logging
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any

from ..constants import TASK_WATCHDOG_INTERVAL

if TYPE_CHECKING:  # pragma: no cover
    from bot.manager import BotManager

_rng = SystemRandom()


class TaskWatchdog:
    def __init__(self, manager: BotManager) -> None:
        self.manager = manager

    def start(self) -> asyncio.Task[Any]:
        return asyncio.create_task(self._loop())

    async def _loop(self) -> None:  # pragma: no cover (timing heavy)
        while self.manager.running and not self.manager.shutdown_initiated:
            try:
                jitter = _rng.uniform(0.7, 1.3)
                await asyncio.sleep(TASK_WATCHDOG_INTERVAL * jitter)
                if not self.manager.running or self.manager.shutdown_initiated:
                    break
                logging.debug("🕰️ Task watchdog tick")
                self._check_task_health()
            except asyncio.CancelledError:
                logging.warning("🛑 Task watchdog cancelled")
                raise
            except Exception as e:  # noqa: BLE001
                logging.error(f"💥 Task watchdog error: {str(e)}")
                await asyncio.sleep(30)

    def _check_task_health(self) -> None:
        dead: list[int] = []
        alive: list[asyncio.Task[Any]] = []
        for i, task in enumerate(self.manager.tasks):
            if task.done():
                if task.exception():
                    logging.warning(
                        f"💥 Task exception index={i}: {str(task.exception())}"
                    )
                else:
                    logging.info(f"✅ Task completed index={i}")
                dead.append(i)
            else:
                alive.append(task)
        if dead:
            self.manager.tasks = alive
            logging.warning(f"🧹 Removed dead tasks (count={len(dead)})")
        else:
            logging.debug("🟢 All tasks alive")
