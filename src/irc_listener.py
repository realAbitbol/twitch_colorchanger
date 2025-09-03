"""Listener loop extracted from async_irc for clarity & testability."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .constants import ASYNC_IRC_READ_TIMEOUT
from .logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class IRCListener:
    """Owns the read loop and delegates message handling & heartbeat checks."""

    def __init__(self, client: AsyncTwitchIRC):
        self.client = client

    async def listen(self):  # noqa: C901 - main loop kept readable
        if not self._can_start_listening():
            return
        self._initialize_listening()
        try:
            while self.client.running and self.client.connected:
                should_break = await self._process_read_cycle()
                if should_break:
                    break
        finally:
            self._finalize_listening()

    def _can_start_listening(self) -> bool:
        if not self.client.connected or not self.client.reader:
            logger.log_event(
                "irc",
                "listen_start_failed",
                level=logging.ERROR,
                user=self.client.username,
            )
            return False
        return True

    def _initialize_listening(self):
        logger.log_event("irc", "listener_start", user=self.client.username)
        self.client.running = True
        import time as _t

        self.client.last_server_activity = _t.time()

    async def _process_read_cycle(self) -> bool:
        try:
            return await self._handle_data_read()
        except TimeoutError:
            return self._handle_read_timeout()
        except Exception as e:  # pragma: no cover - defensive
            logger.log_event(
                "irc",
                "connection_reset",
                level=logging.ERROR,
                user=self.client.username,
                error=str(e),
            )
            return True

    async def _handle_data_read(self) -> bool:
        if not self.client.reader:
            logger.log_event(
                "irc", "no_reader", level=logging.ERROR, user=self.client.username
            )
            return True
        data = await asyncio.wait_for(
            self.client.reader.read(4096), timeout=ASYNC_IRC_READ_TIMEOUT
        )
        if not data:
            logger.log_event(
                "irc", "connection_lost", level=logging.ERROR, user=self.client.username
            )
            self.client.connected = False
            return True
        decoded_data = data.decode("utf-8", errors="ignore")
        self.client.message_buffer = await self.client.dispatcher.process_incoming_data(  # type: ignore[attr-defined]
            self.client.message_buffer, decoded_data
        )
        return self.client.heartbeat.perform_periodic_checks()  # type: ignore[attr-defined]

    def _handle_read_timeout(self) -> bool:
        if self.client.heartbeat.is_connection_stale():  # type: ignore[attr-defined]
            logger.log_event(
                "irc",
                "connection_stale",
                level=logging.WARNING,
                user=self.client.username,
            )
            self.client.connected = False
            return True
        return False

    def _finalize_listening(self):
        self.client.running = False
        logger.log_event(
            "irc", "listener_stopped", level=logging.WARNING, user=self.client.username
        )
        if not self.client.writer or not self.client.reader:
            self.client.connected = False
