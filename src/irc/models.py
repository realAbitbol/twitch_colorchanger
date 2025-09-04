"""Shared IRC data models (packaged)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    JOINING = auto()
    JOINED = auto()


@dataclass(slots=True)
class ChannelJoinStatus:
    channel: str
    confirmed: bool = False
