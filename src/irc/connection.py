"""Connection & reconnection logic for Twitch IRC (packaged)."""

from __future__ import annotations

import asyncio
import secrets
import time
from enum import Enum, auto
from typing import TYPE_CHECKING

from constants import (
    ASYNC_IRC_RECONNECT_TIMEOUT,
    BACKOFF_BASE_DELAY,
    BACKOFF_JITTER_FACTOR,
    BACKOFF_MAX_DELAY,
    BACKOFF_MULTIPLIER,
    RECONNECT_DELAY,
)
from logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    AUTHENTICATING = auto()
    JOINING = auto()
    READY = auto()
    RECONNECTING = auto()
    DEGRADED = auto()


class IRCConnectionController:
    """Handles reconnection and backoff using host AsyncTwitchIRC instance."""

    def __init__(self, host: AsyncTwitchIRC) -> None:
        self.host = host

    async def force_reconnect(self) -> bool:
        host = self.host
        async with host._reconnect_lock:  # pylint: disable=protected-access
            if not host.username or not host.token or not host.channels:
                logger.log_event(
                    "irc", "reconnect_missing_details", level=40, user=host.username
                )
                return False

            host._set_state(ConnectionState.RECONNECTING)  # pylint: disable=protected-access
            logger.log_event("irc", "force_reconnect", level=30, user=host.username)

            # Backoff check
            now = time.time()
            time_since_last_attempt = now - host.last_reconnect_attempt
            backoff_delay = self._calculate_backoff_delay(host.consecutive_failures)
            if time_since_last_attempt < backoff_delay:
                remaining = backoff_delay - time_since_last_attempt
                logger.log_event(
                    "irc",
                    "reconnect_backoff_wait",
                    level=30,
                    user=host.username,
                    remaining_wait=remaining,
                    attempt=host.consecutive_failures + 1,
                )
                await asyncio.sleep(remaining)

            original_channels = host.channels.copy()

            # Disconnect first
            await host.disconnect()
            await asyncio.sleep(RECONNECT_DELAY)

            host.last_reconnect_attempt = time.time()
            host.consecutive_failures += 1

            channel = original_channels[0] if original_channels else ""
            try:
                success = await asyncio.wait_for(
                    host.connect(host.token, host.username, channel),  # type: ignore[arg-type]
                    timeout=ASYNC_IRC_RECONNECT_TIMEOUT,
                )
            except TimeoutError:
                logger.log_event(
                    "irc",
                    "reconnect_timeout",
                    level=40,
                    user=host.username,
                    timeout=ASYNC_IRC_RECONNECT_TIMEOUT,
                )
                success = False

            if success:
                host.consecutive_failures = 0
                now = time.time()
                host.last_ping_from_server = now
                host.last_server_activity = now
                host.channels = original_channels
                host._join_grace_deadline = time.time() + 30  # pylint: disable=protected-access
                logger.log_event(
                    "irc",
                    "reconnect_success",
                    user=host.username,
                    extra_channels=len(host.channels) - 1,
                )
            else:
                logger.log_event(
                    "irc",
                    "reconnect_failed",
                    level=40,
                    user=host.username,
                    attempt=host.consecutive_failures,
                )

            if success:
                if host.is_healthy():
                    host._set_state(ConnectionState.READY)  # pylint: disable=protected-access
                else:
                    host._set_state(ConnectionState.DEGRADED)  # pylint: disable=protected-access
            else:
                host._set_state(ConnectionState.DISCONNECTED)  # pylint: disable=protected-access
            return success

    @staticmethod
    def _calculate_backoff_delay(consecutive_failures: int) -> float:
        if consecutive_failures == 0:
            return 0.0
        delay = BACKOFF_BASE_DELAY * (BACKOFF_MULTIPLIER ** (consecutive_failures - 1))
        delay = min(delay, BACKOFF_MAX_DELAY)
        jitter = (
            delay * BACKOFF_JITTER_FACTOR * (secrets.SystemRandom().random() * 2 - 1)
        )
        delay += jitter
        return max(0.0, delay)
