"""Health checking helpers (packaged)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class IRCHealthMonitor:
    def __init__(self, host: AsyncTwitchIRC) -> None:
        self.host = host

    def get_connection_stats(self) -> dict[str, Any]:
        host = self.host
        current_time = time.time()
        time_since_activity = current_time - host.last_server_activity
        return {
            "connected": host.connected,
            "running": host.running,
            "channels": list(host.channels),
            "confirmed_channels": list(host.confirmed_channels),
            "last_server_activity": host.last_server_activity,
            "last_ping_from_server": host.last_ping_from_server,
            "time_since_activity": time_since_activity,
            "time_since_last_activity": time_since_activity,
            "time_since_last_ping": (
                current_time - host.last_ping_from_server
                if host.last_ping_from_server > 0
                else 0
            ),
            "consecutive_failures": host.consecutive_failures,
            "pending_joins": len(host.pending_joins),
            "is_healthy": self.is_healthy(),
        }

    def is_healthy(self) -> bool:
        snap = self.get_health_snapshot()
        healthy = snap.get("healthy")
        return bool(healthy)

    def get_health_snapshot(self) -> dict[str, Any]:
        host = self.host
        reasons: list[str] = []
        current_time = time.time()
        self._check_basic_connection_health(reasons)
        time_since_activity = self._check_activity_health(reasons, current_time)
        self._check_ping_health(reasons, current_time)
        self._check_operational_health(reasons)
        if (
            host._join_grace_deadline  # noqa: SLF001
            and current_time < host._join_grace_deadline  # noqa: SLF001
            and "pending_joins" in reasons
        ):
            reasons.remove("pending_joins")
        return {
            "username": host.username,
            "state": host.state.name,
            "connection_state": host.state.name,
            "healthy": len(reasons) == 0,
            "reasons": reasons,
            "connected": host.connected,
            "running": host.running,
            "time_since_activity": time_since_activity,
            "time_since_ping": (
                current_time - host.last_ping_from_server
                if host.last_ping_from_server > 0
                else None
            ),
            "pending_joins": len(host.pending_joins),
            "consecutive_failures": host.consecutive_failures,
            "has_streams": host.reader is not None and host.writer is not None,
        }

    def _check_basic_connection_health(self, reasons: list[str]) -> None:
        h = self.host
        if not h.connected:
            reasons.append("not_connected")
        if not h.running:
            reasons.append("not_running")
        if not h.reader or not h.writer:
            reasons.append("missing_streams")

    def _check_activity_health(
        self, reasons: list[str], current_time: float
    ) -> float | None:
        h = self.host
        time_since_activity = (
            current_time - h.last_server_activity
            if h.last_server_activity > 0
            else None
        )
        if time_since_activity is not None:
            if time_since_activity > (h.server_activity_timeout * 0.5):
                reasons.append("idle_warning")
            if time_since_activity > h.server_activity_timeout:
                reasons.append("stale_activity")
        return time_since_activity

    def _check_ping_health(self, reasons: list[str], current_time: float) -> None:
        h = self.host
        if h.last_ping_from_server > 0:
            ping_timeout = h.expected_ping_interval * 1.5
            if current_time - h.last_ping_from_server > ping_timeout:
                reasons.append("ping_timeout")

    def _check_operational_health(self, reasons: list[str]) -> None:
        h = self.host
        if h.pending_joins:
            reasons.append("pending_joins")
        if h.consecutive_failures > 0:
            reasons.append("recent_failures")
