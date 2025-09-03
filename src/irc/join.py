"""Join workflow manager (packaged)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..constants import ASYNC_IRC_JOIN_TIMEOUT
from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class IRCJoinManager:
    def __init__(self, client: AsyncTwitchIRC):
        self.client = client

    async def join_with_message_processing(self, channel: str) -> bool:
        channel = channel.lower()
        if channel in self.client.confirmed_channels:
            logger.log_event(
                "irc",
                "join_already_confirmed",
                level=logging.DEBUG,
                user=self.client.username,
                channel=channel,
            )
            return True
        logger.log_event(
            "irc", "join_start", user=self.client.username, channel=channel
        )
        try:
            await self.client._send_line(f"JOIN #{channel}")  # noqa: SLF001
            return await self._wait_for_join_confirmation(channel)
        except Exception as e:  # pragma: no cover - defensive
            logger.log_event(
                "irc",
                "join_error",
                level=logging.ERROR,
                user=self.client.username,
                channel=channel,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def _wait_for_join_confirmation(self, channel: str) -> bool:
        start_time = time.time()
        message_buffer = ""
        while time.time() - start_time < ASYNC_IRC_JOIN_TIMEOUT:
            try:
                data = await self._read_join_data()
                if data is None:
                    return False
                decoded_data = data.decode("utf-8", errors="ignore")
                message_buffer = await self.client.dispatcher.process_incoming_data(  # type: ignore[attr-defined]
                    message_buffer, decoded_data
                )
                if channel in self.client.confirmed_channels:
                    return self._finalize_channel_join(channel)
            except TimeoutError:
                continue
            except ConnectionResetError:
                self._log_connection_reset_error()
                return False
            except Exception as e:  # pragma: no cover - defensive
                logger.log_event(
                    "irc",
                    "join_processing_error",
                    level=logging.ERROR,
                    user=self.client.username,
                    channel=channel,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return False
        self._log_join_timeout(channel)
        return False

    async def _read_join_data(self) -> bytes | None:
        if not self.client.reader:
            logger.log_event(
                "irc", "join_no_reader", level=logging.ERROR, user=self.client.username
            )
            return None
        data = await asyncio.wait_for(self.client.reader.read(4096), timeout=0.5)
        if not data:
            logger.log_event(
                "irc",
                "join_connection_lost",
                level=logging.ERROR,
                user=self.client.username,
            )
            return None
        return data

    def _finalize_channel_join(self, channel: str) -> bool:
        if channel not in self.client.channels:
            self.client.channels.append(channel)
        logger.log_event(
            "irc", "join_success", user=self.client.username, channel=channel
        )
        return True

    def _log_connection_reset_error(self):  # pragma: no cover - logging only
        reset_msg = (
            f"❌ {self.client.username}: Connection reset by server - "
            "likely authentication failure"
        )
        logger.log_event(
            "irc",
            "connection_reset",
            level=logging.ERROR,
            user=self.client.username,
            message=reset_msg,
        )

    def _log_join_timeout(self, channel: str):  # pragma: no cover - logging only
        logger.log_event(
            "irc",
            "join_timeout",
            level=logging.ERROR,
            user=self.client.username,
            channel=channel,
        )

    async def join_channel(self, channel: str) -> bool:
        channel = channel.lower()
        if channel in self.client.confirmed_channels:
            logger.log_event(
                "irc",
                "join_already_confirmed",
                level=logging.DEBUG,
                user=self.client.username,
                channel=channel,
            )
            return True
        self.client.pending_joins[channel] = {
            "attempts": self.client.pending_joins.get(channel, {}).get("attempts", 0)
            + 1,
            "timestamp": time.time(),
        }
        attempts = self.client.pending_joins[channel]["attempts"]  # type: ignore[index]
        if attempts > self.client.max_join_attempts:
            logger.log_event(
                "irc",
                "join_max_attempts",
                level=logging.ERROR,
                user=self.client.username,
                channel=channel,
            )
            return False
        logger.log_event(
            "irc",
            "join_attempt",
            user=self.client.username,
            channel=channel,
            attempt=attempts,
        )
        try:
            await self.client._send_line(f"JOIN #{channel}")  # noqa: SLF001
            start_time = time.time()
            while time.time() - start_time < ASYNC_IRC_JOIN_TIMEOUT:
                if channel in self.client.confirmed_channels:
                    self.client.pending_joins.pop(channel, None)
                    if channel not in self.client.channels:
                        self.client.channels.append(channel)
                    logger.log_event(
                        "irc",
                        "join_success",
                        user=self.client.username,
                        channel=channel,
                    )
                    return True
                await asyncio.sleep(0.1)
            logger.log_event(
                "irc",
                "join_timeout",
                level=logging.WARNING,
                user=self.client.username,
                channel=channel,
            )
            self.client.pending_joins.pop(channel, None)
            return False
        except Exception as e:  # pragma: no cover - defensive
            logger.log_event(
                "irc",
                "join_error",
                level=logging.ERROR,
                user=self.client.username,
                channel=channel,
                error=str(e),
                error_type=type(e).__name__,
            )
            self.client.pending_joins.pop(channel, None)
            return False
