"""Task watchdog extracted from BotManager to isolate task supervision."""

from __future__ import annotations

import asyncio
from secrets import SystemRandom
from typing import TYPE_CHECKING, Any

from ..constants import TASK_WATCHDOG_INTERVAL
from ..logs.logger import logger

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
                logger.log_event("manager", "task_watchdog_tick", level=10)
                self._check_task_health()
            except asyncio.CancelledError:
                logger.log_event("manager", "task_watchdog_cancelled", level=30)
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "manager", "task_watchdog_error", level=40, error=str(e)
                )
                await asyncio.sleep(30)

    def _check_task_health(self) -> None:
        dead: list[int] = []
        alive: list[asyncio.Task[Any]] = []
        for i, task in enumerate(self.manager.tasks):
            if task.done():
                if task.exception():
                    logger.log_event(
                        "manager",
                        "task_exception_detected",
                        level=30,
                        index=i,
                        error=str(task.exception()),
                    )
                else:
                    logger.log_event("manager", "task_completed", index=i)
                dead.append(i)
            else:
                alive.append(task)
        if dead:
            self.manager.tasks = alive
            logger.log_event("manager", "removed_dead_tasks", level=30, count=len(dead))
        else:
            logger.log_event("manager", "all_tasks_alive", level=10)
