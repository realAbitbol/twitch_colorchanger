"""Wrapper adapting existing AsyncTwitchIRC to ChatBackend interface."""

from __future__ import annotations

from typing import Any

from ..irc.async_irc import AsyncTwitchIRC
from ..logs.logger import logger
from .abstract import ChatBackend, MessageHandler


class IRCChatBackend(ChatBackend):
    def __init__(self) -> None:
        self._irc = AsyncTwitchIRC()

    async def connect(
        self,
        token: str,
        username: str,
        primary_channel: str,
        user_id: str | None,
        client_id: str | None,  # ignored
        client_secret: str | None = None,  # ignored
    ) -> bool:  # noqa: D401
        _ = user_id  # user_id not needed for IRC
        _ = client_id
        _ = client_secret
        return await self._irc.connect(token, username, primary_channel)

    async def join_channel(self, channel: str) -> bool:
        return await self._irc.join_channel(channel)

    async def listen(self) -> None:
        await self._irc.listen()

    async def disconnect(self) -> None:
        await self._irc.disconnect()

    def update_token(self, new_token: str) -> None:
        self._irc.update_token(new_token)

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._irc.set_message_handler(handler)

    def set_color_change_handler(self, handler: MessageHandler) -> None:
        try:
            self._irc.set_color_change_handler(handler)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat",
                "irc_color_handler_set_error",
                level=20,
                error=str(e),
            )

    # Convenience to expose health / stats if callers still expect them.
    def get_connection_stats(self) -> dict[str, Any]:  # pragma: no cover - passthrough
        return self._irc.get_connection_stats()

    def is_healthy(self) -> bool:  # pragma: no cover - passthrough
        return self._irc.is_healthy()
