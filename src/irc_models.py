"""IRC message model definitions (extracted from async_irc)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IRCMessage:
    """Generic parsed IRC message (without IRCv3 tags)."""

    raw: str
    prefix: str | None
    command: str
    params: str

    def is_privmsg(self) -> bool:  # convenience
        return self.command.upper() == "PRIVMSG"


@dataclass(slots=True)
class PrivMsg:
    """Structured PRIVMSG payload."""

    channel: str
    author: str
    message: str
