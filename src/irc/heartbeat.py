"""Heartbeat & periodic connection health checks (packaged)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class IRCHeartbeat:
    def __init__(self, client: AsyncTwitchIRC):
        self.client = client

    def perform_periodic_checks(self) -> bool:
        current_time = time.time()
        activity_timeout = self.client.server_activity_timeout
        if current_time - self.client.last_server_activity > activity_timeout:
            logger.log_event(
                "irc",
                "no_server_activity",
                level=logging.WARNING,
                user=self.client.username,
                timeout=self.client.server_activity_timeout,
            )
            return True
        ping_timeout = self.client.expected_ping_interval * 1.5
        if (
            self.client.last_ping_from_server > 0
            and current_time - self.client.last_ping_from_server > ping_timeout
        ):
            time_since_ping = current_time - self.client.last_ping_from_server
            logger.log_event(
                "irc",
                "ping_timeout",
                level=logging.WARNING,
                user=self.client.username,
                time_since_ping=time_since_ping,
            )
            return True
        return False

    def is_connection_stale(self) -> bool:
        current_time = time.time()
        time_since_activity = current_time - self.client.last_server_activity
        early_stale_threshold = self.client.server_activity_timeout * 0.25
        if time_since_activity > early_stale_threshold:
            logger.log_event(
                "irc",
                "stale_early_warning",
                level=logging.DEBUG,
                user=self.client.username,
                time_since_activity=time_since_activity,
            )
        return time_since_activity > (self.client.server_activity_timeout / 2)
