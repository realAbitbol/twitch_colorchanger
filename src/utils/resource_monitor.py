"""Resource monitoring and leak detection utilities for long-running applications."""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import psutil


@dataclass
class ResourceSnapshot:
    """Snapshot of system resource usage."""

    timestamp: float
    memory_mb: float
    open_files: int
    connections: int
    gc_objects: int
    asyncio_tasks: int


@dataclass
class ResourceMetrics:
    """Resource usage metrics over time."""

    snapshots: list[ResourceSnapshot] = field(default_factory=list)
    max_snapshots: int = 100
    leak_threshold_mb: float = 50.0  # MB
    leak_check_interval: float = 300.0  # 5 minutes

    def add_snapshot(self, snapshot: ResourceSnapshot) -> None:
        """Add a resource snapshot."""
        self.snapshots.append(snapshot)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots.pop(0)

    def detect_memory_leak(self) -> bool:
        """Detect potential memory leaks."""
        if len(self.snapshots) < 2:
            return False

        # Compare recent snapshots
        recent = self.snapshots[-5:] if len(self.snapshots) >= 5 else self.snapshots
        if len(recent) < 2:
            return False

        # Check for steady memory increase
        memory_trend = recent[-1].memory_mb - recent[0].memory_mb
        return memory_trend > self.leak_threshold_mb


class ResourceMonitor:
    """Monitor system resources and detect leaks."""

    def __init__(self):
        self.metrics = ResourceMetrics()
        self._process = psutil.Process()
        self._monitoring = False
        self._monitor_task: asyncio.Task[Any] | None = None

    async def start_monitoring(self) -> None:
        """Start resource monitoring."""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logging.info("🔍 Resource monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop resource monitoring."""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logging.info("⏹️ Resource monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._monitoring:
            try:
                snapshot = self._take_snapshot()
                self.metrics.add_snapshot(snapshot)

                # Check for leaks
                if self.metrics.detect_memory_leak():
                    logging.warning(
                        f"🚨 Potential memory leak detected: {snapshot.memory_mb:.1f}MB"
                    )

                await asyncio.sleep(self.metrics.leak_check_interval)
            except Exception as e:
                logging.error(f"Resource monitoring error: {e}")
                await asyncio.sleep(60.0)  # Wait before retrying

    def _take_snapshot(self) -> ResourceSnapshot:
        """Take a snapshot of current resource usage."""
        try:
            memory_info = self._process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024

            # Count open files (approximate)
            try:
                open_files = len(self._process.open_files())
            except (psutil.AccessDenied, AttributeError):
                open_files = 0

            # Count network connections (approximate)
            try:
                connections = len(self._process.connections())
            except (psutil.AccessDenied, AttributeError):
                connections = 0

            # Count asyncio tasks (approximate)
            try:
                all_tasks = asyncio.all_tasks()
                asyncio_tasks = len(all_tasks)
            except RuntimeError:
                asyncio_tasks = 0

            return ResourceSnapshot(
                timestamp=time.monotonic(),
                memory_mb=memory_mb,
                open_files=open_files,
                connections=connections,
                gc_objects=len(gc.get_objects()),
                asyncio_tasks=asyncio_tasks,
            )
        except Exception as e:
            logging.warning(f"Failed to take resource snapshot: {e}")
            # Return minimal snapshot on error
            return ResourceSnapshot(
                timestamp=time.monotonic(),
                memory_mb=0.0,
                open_files=0,
                connections=0,
                gc_objects=0,
                asyncio_tasks=0,
            )

    def get_latest_snapshot(self) -> ResourceSnapshot | None:
        """Get the latest resource snapshot."""
        return self.metrics.snapshots[-1] if self.metrics.snapshots else None

    def force_garbage_collection(self) -> None:
        """Force garbage collection to help detect leaks."""
        gc.collect()
        logging.debug("🗑️ Forced garbage collection")


# Global resource monitor instance
_resource_monitor: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    """Get the global resource monitor instance."""
    global _resource_monitor
    if _resource_monitor is None:
        _resource_monitor = ResourceMonitor()
    return _resource_monitor


async def start_resource_monitoring() -> None:
    """Start global resource monitoring."""
    monitor = get_resource_monitor()
    await monitor.start_monitoring()


async def stop_resource_monitoring() -> None:
    """Stop global resource monitoring."""
    monitor = get_resource_monitor()
    await monitor.stop_monitoring()


def log_resource_usage() -> None:
    """Log current resource usage."""
    monitor = get_resource_monitor()
    snapshot = monitor.get_latest_snapshot()

    if snapshot:
        logging.info(
            f"📊 Resource usage: "
            f"Memory={snapshot.memory_mb:.1f}MB, "
            f"Files={snapshot.open_files}, "
            f"Connections={snapshot.connections}, "
            f"Tasks={snapshot.asyncio_tasks}"
        )
    else:
        logging.debug("No resource snapshot available")
