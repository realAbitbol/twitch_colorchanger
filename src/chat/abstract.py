"""Chat backend abstraction layer.

This introduces a unified interface so the bot can switch between:
 - Traditional IRC (existing implementation)  (backend id: "irc")
 - EventSub WebSocket (channel.chat.message) (backend id: "eventsub")

Minimal contract (kept small to ease wrapping the existing IRC client):
    connect(token: str, username: str, primary_channel: str, user_id: str | None) -> bool
    join_channel(channel: str) -> bool | Awaitable[bool]
    listen() -> Awaitable[None]  (long running)
    disconnect() -> Awaitable[None]
    update_token(new_token: str) -> None
    set_message_handler(callable(username, channel, message))
    set_color_change_handler(callable(username, channel, message))  (optional feature parity)

Message handler semantics mirror previous AsyncTwitchIRC expectations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any

MessageHandler = Callable[[str, str, str], Any]


class ChatBackend(ABC):
    """Abstract chat backend interface."""

    @abstractmethod
    async def connect(
        self,
        token: str,
        username: str,
        primary_channel: str,
        user_id: str | None,
        client_id: str | None,
        client_secret: str | None = None,
    ) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def join_channel(self, channel: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def listen(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    def update_token(self, new_token: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    def set_message_handler(
        self, handler: MessageHandler
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def set_color_change_handler(self, handler: MessageHandler) -> None:  # optional
        # Default no-op; IRC backend overrides.
        _ = handler


class BackendType(str, Enum):
    IRC = "irc"
    EVENTSUB = "eventsub"


def normalize_backend_type(raw: str | None) -> BackendType:
    if not raw:
        return BackendType.IRC
    lowered = raw.strip().lower()
    if lowered in {"eventsub", "event_sub", "es"}:
        return BackendType.EVENTSUB
    return BackendType.IRC
