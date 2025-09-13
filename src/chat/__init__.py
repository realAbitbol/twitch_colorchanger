"""Chat backend factory & exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .abstract import BackendType, ChatBackend, normalize_backend_type
from .eventsub_backend import EventSubChatBackend

__all__ = [
    "BackendType",
    "ChatBackend",
    "normalize_backend_type",
    "create_chat_backend",
]

if TYPE_CHECKING:  # pragma: no cover
    import aiohttp


def create_chat_backend(
    kind: str | None, http_session: aiohttp.ClientSession | None = None
) -> ChatBackend:
    btype = normalize_backend_type(kind)
    if btype == BackendType.EVENTSUB:
        return EventSubChatBackend(http_session=http_session)
    raise ValueError(f"Unsupported backend type: {btype}")
