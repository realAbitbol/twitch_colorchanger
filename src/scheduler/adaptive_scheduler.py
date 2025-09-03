"""
Adaptive scheduler for managing periodic tasks with priority-based timing
"""

import asyncio
import heapq
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..logs.logger import logger


@dataclass
class ScheduledTask:
    """Represents a scheduled task"""

    # Using __slots__ for better performance with many tasks
    __slots__ = [
        "next_run",
        "callback",
        "name",
        "interval",
        "args",
        "kwargs",
        "priority",
    ]

    next_run: float  # Monotonic timestamp when task should run
    callback: Callable
    name: str
    interval: float | None  # None for one-time tasks
    args: tuple
    kwargs: dict
    priority: int  # Lower number = higher priority

    def __post_init__(self):
        """Set default priority if not provided"""
        if not hasattr(self, "priority") or self.priority is None:
            self.priority = 0

    def __lt__(self, other):
        """For heap ordering - compare by next_run time, then priority"""
        if self.next_run != other.next_run:
            return self.next_run < other.next_run
        return self.priority < other.priority


class AdaptiveScheduler:
    """
    Manages periodic tasks using a min-heap for efficient scheduling.

    Features:
    - Adaptive delays based on task requirements
    - Priority-based scheduling
    - Graceful cancellation handling
    - Memory-efficient with monotonic timing
    """

    def __init__(self):
        self.tasks: list[ScheduledTask] = []
        self.running = False
        self.scheduler_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the scheduler"""
        if self.running:
            return

        self.running = True
        # Use async context for task creation
        async with self._lock:
            self.scheduler_task = asyncio.create_task(self._run_scheduler())

    logger.log_event("scheduler", "started")

    async def stop(self):
        """Stop the scheduler and cancel all tasks"""
        if not self.running:
            return

        self.running = False

        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                # Cleanup: Clear running flag on cancellation
                self.running = False
                # Re-raise as per asyncio best practices
                raise

        # Clear all tasks
        async with self._lock:
            self.tasks.clear()

    logger.log_event("scheduler", "stopped", level=logging.WARNING)

    async def schedule_recurring(  # noqa: D401
        self,
        callback: Callable,
        interval: float,
        name: str,
        *args,
        priority: int = 0,
        initial_delay: float = 0,
        **kwargs,
    ) -> bool:
        """
        Schedule a recurring task

        Args:
            callback: Function to call
            interval: Seconds between calls
            name: Task name for logging
            priority: Task priority (lower = higher priority)
            initial_delay: Delay before first execution
            *args, **kwargs: Arguments for callback

        Returns:
            True if scheduled successfully
        """
        if not self.running:
            return False

        next_run = time.monotonic() + initial_delay
        task = ScheduledTask(
            next_run=next_run,
            callback=callback,
            name=name,
            interval=interval,
            args=args,
            kwargs=kwargs,
            priority=priority,
        )

        async with self._lock:
            heapq.heappush(self.tasks, task)

        logger.log_event(
            "scheduler",
            "scheduled_recurring",
            level=logging.DEBUG,
            task=name,
            interval=interval,
        )
        return True

    async def schedule_once(  # noqa: D401
        self,
        callback: Callable,
        delay: float,
        name: str,
        *args,
        priority: int = 0,
        **kwargs,
    ) -> bool:
        """
        Schedule a one-time task

        Args:
            callback: Function to call
            delay: Seconds until execution
            name: Task name for logging
            priority: Task priority (lower = higher priority)
            *args, **kwargs: Arguments for callback

        Returns:
            True if scheduled successfully
        """
        if not self.running:
            return False

        next_run = time.monotonic() + delay
        task = ScheduledTask(
            next_run=next_run,
            callback=callback,
            name=name,
            interval=None,  # One-time task
            args=args,
            kwargs=kwargs,
            priority=priority,
        )

        async with self._lock:
            heapq.heappush(self.tasks, task)

        logger.log_event(
            "scheduler", "scheduled_once", level=logging.DEBUG, task=name, delay=delay
        )
        return True

    async def cancel_task(self, name: str) -> bool:  # noqa: D401
        """Cancel all tasks with the given name"""
        if not self.running:
            return False

        async with self._lock:
            # Remove tasks with matching name
            self.tasks = [task for task in self.tasks if task.name != name]
            heapq.heapify(self.tasks)  # Rebuild heap

        logger.log_event("scheduler", "cancelled_tasks_named", task=name)
        return True

    async def reschedule_task(self, name: str, new_interval: float) -> bool:  # noqa: D401
        """Update the interval for a recurring task"""
        if not self.running:
            return False

        async with self._lock:
            for task in self.tasks:
                if task.name == name and task.interval is not None:
                    task.interval = new_interval
                    # Update next run time based on new interval
                    current_time = time.monotonic()
                    task.next_run = current_time + new_interval
                    heapq.heapify(self.tasks)  # Rebuild heap
                    logger.log_event(
                        "scheduler",
                        "rescheduled_task",
                        level=logging.DEBUG,
                        task=name,
                        interval=new_interval,
                    )
                    return True

        return False

    def get_next_task_delay(self) -> float:  # noqa: D401
        """Get delay until next task (for debugging/monitoring)"""
        if not self.tasks:
            return float("inf")

        next_task = self.tasks[0]
        delay = next_task.next_run - time.monotonic()
        return max(0, delay)

    def get_task_count(self) -> int:  # noqa: D401
        """Get number of scheduled tasks"""
        return len(self.tasks)

    # Removed get_health_status (unused).  # noqa: ERA001

    async def _run_scheduler(self):
        """Main scheduler loop"""
        while self.running:
            try:
                await self._process_next_batch()

            except asyncio.CancelledError:
                logger.log_event(
                    "scheduler", "scheduler_cancelled", level=logging.DEBUG
                )
                raise

            except Exception as e:
                logger.log_event(
                    "scheduler", "scheduler_error", level=logging.ERROR, error=str(e)
                )
                # Wait a bit before retrying to avoid tight error loops
                await asyncio.sleep(1.0)

    async def _process_next_batch(self):
        """Process the next batch of ready tasks"""
        current_time = time.monotonic()
        tasks_to_run = []
        tasks_to_reschedule = []

        # Get tasks ready to run
        async with self._lock:
            while self.tasks and self.tasks[0].next_run <= current_time:
                task = heapq.heappop(self.tasks)
                tasks_to_run.append(task)

                # If it's a recurring task, prepare to reschedule
                if task.interval is not None:
                    task.next_run = current_time + task.interval
                    tasks_to_reschedule.append(task)

            # Reschedule recurring tasks
            for task in tasks_to_reschedule:
                heapq.heappush(self.tasks, task)

        # Execute ready tasks (outside the lock to avoid blocking)
        for task in tasks_to_run:
            await self._execute_task(task)

        # Calculate sleep time until next task
        if self.tasks:
            next_task_time = self.tasks[0].next_run
            sleep_time = max(0.1, next_task_time - time.monotonic())
        else:
            sleep_time = 1.0  # Default sleep when no tasks

        await asyncio.sleep(min(sleep_time, 5.0))  # Cap at 5 seconds

    async def _execute_task(self, task: ScheduledTask):
        """Execute a single task with error handling"""
        try:
            if asyncio.iscoroutinefunction(task.callback):
                await task.callback(*task.args, **task.kwargs)
            else:
                task.callback(*task.args, **task.kwargs)

        except asyncio.CancelledError:
            # Don't log cancelled tasks as errors
            logger.log_event(
                "scheduler", "task_cancelled", level=logging.DEBUG, task=task.name
            )
            # Re-raise as per asyncio best practices
            raise

        except Exception as e:
            logger.log_event(
                "scheduler",
                "task_failed",
                level=logging.ERROR,
                task=task.name,
                error=str(e),
            )
