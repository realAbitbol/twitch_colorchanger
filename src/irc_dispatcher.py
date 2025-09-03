"""Message dispatch & parsing logic extracted from async_irc."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING

from .irc_parser import build_privmsg, parse_irc_message
from .logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .async_irc import AsyncTwitchIRC


class IRCDispatcher:
    """Parses incoming data, processes IRC messages, and dispatches handlers."""

    def __init__(self, client: AsyncTwitchIRC):
        self.client = client

    async def process_incoming_data(self, buffer: str, new_data: str) -> str:
        buffer += new_data
        self.client.last_server_activity = self.client.last_server_activity = (
            __import__("time").time()
        )
        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)
            if line.strip():
                await self._handle_irc_message(line.strip())
        return buffer

    async def _handle_irc_message(self, raw_message: str):  # noqa: C901 - kept flat
        if not raw_message.startswith("PING"):
            logger.log_event(
                "irc",
                "raw",
                level=logging.DEBUG,
                user=self.client.username,
                raw=raw_message,
            )

        if raw_message.startswith("PING"):
            await self._handle_ping(raw_message)
            return

        parsed = parse_irc_message(raw_message)
        command = parsed.command
        if not command:
            return
        if command in ["366", "RPL_ENDOFNAMES"]:
            self._handle_channel_confirmation(parsed.params)
        elif command == "PRIVMSG" and parsed.prefix:
            await self._handle_privmsg(parsed)

    async def _handle_ping(self, raw_message: str):
        server = raw_message.split(":", 1)[1] if ":" in raw_message else "tmi.twitch.tv"
        pong = f"PONG :{server}"
        await self.client._send_line(pong)  # noqa: SLF001
        self.client.last_ping_from_server = __import__("time").time()

    def _handle_channel_confirmation(self, params: str):
        if " #" in params:
            channel = params.split(" #")[1].split()[0].lower()
            self.client.confirmed_channels.add(channel)
            self.client.joined_channels.add(channel)

    async def _handle_privmsg(self, parsed):  # type: ignore[no-untyped-def]
        priv = build_privmsg(parsed)
        if not priv:
            return
        self._log_chat_message(priv.author, priv.channel, priv.message)
        await self._process_message_handlers(priv.author, priv.channel, priv.message)
        await self._handle_color_change_command(priv.author, priv.channel, priv.message)

    def _log_chat_message(self, username: str, channel: str, message: str):
        is_bot_message = (
            username.lower() == self.client.username.lower()
            if self.client.username
            else False
        )
        if is_bot_message:
            logger.log_event(
                "irc",
                "privmsg",
                user=self.client.username,
                human=f"{username}: {message}",
                author=username,
                channel=channel,
                chat_message=message,
                self_message=True,
            )
        else:
            logger.log_event(
                "irc",
                "privmsg",
                level=logging.DEBUG,
                user=self.client.username,
                human=f"{username}: {message}",
                author=username,
                channel=channel,
                chat_message=message,
                self_message=False,
            )

    async def _process_message_handlers(
        self, username: str, channel: str, message: str
    ):
        if not self.client.message_handler:
            logger.log_event(
                "irc",
                "no_message_handler",
                level=logging.WARNING,
                user=self.client.username,
            )
            return
        logger.log_event(
            "irc",
            "dispatch_message_handler",
            level=logging.DEBUG,
            user=self.client.username,
            channel=channel,
            author=username,
        )
        try:
            if inspect.iscoroutinefunction(self.client.message_handler):
                await self.client.message_handler(username, channel, message)  # type: ignore[misc]
            else:
                task = asyncio.create_task(
                    asyncio.to_thread(
                        self.client.message_handler, username, channel, message
                    )  # type: ignore[arg-type]
                )
                await task
            logger.log_event(
                "irc",
                "message_handler_complete",
                level=logging.DEBUG,
                user=self.client.username,
                channel=channel,
                author=username,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.log_event(
                "irc",
                "connect_network_error",
                level=logging.ERROR,
                user=self.client.username,
                channel=channel,
                error=str(e),
            )

    async def _handle_color_change_command(
        self, username: str, channel: str, message: str
    ):
        if not message.startswith("/color ") or not self.client.color_change_handler:
            return
        try:
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.client.color_change_handler,
                    username,
                    channel,
                    message,  # type: ignore[arg-type]
                )
            )
            await task
        except Exception as e:  # pragma: no cover - defensive
            logger.log_event(
                "irc",
                "connect_network_error",
                level=logging.ERROR,
                user=self.client.username,
                channel=channel,
                error=str(e),
            )
