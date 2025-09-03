"""Pure parsing helpers for Twitch IRC messages.

Keeps logic side‑effect free so it can be unit tested easily.
"""

from __future__ import annotations

from .irc_models import IRCMessage, PrivMsg


def parse_irc_message(raw_message: str) -> IRCMessage:
    """Parse a raw IRC line into an IRCMessage.

    Strips IRCv3 tags and splits prefix / command / params.
    Returns empty command if parsing fails (caller can ignore).
    """
    original = raw_message.rstrip("\r\n")
    working = original

    # Remove IRCv3 tags (start with '@' until first space)
    if working.startswith("@"):
        tag_end = working.find(" ")
        if tag_end != -1:
            working = working[tag_end + 1 :]

    parts = working.split(" ", 2)
    if len(parts) < 2:
        return IRCMessage(original, None, "", "")

    if parts[0].startswith(":"):
        prefix = parts[0]
        command = parts[1]
        params = parts[2] if len(parts) > 2 else ""
    else:
        prefix = None
        command = parts[0]
        params = parts[1] if len(parts) > 1 else ""

    return IRCMessage(original, prefix, command, params)


def parse_privmsg_components(
    prefix: str | None, params: str
) -> tuple[str | None, str | None, str | None]:
    """Extract (channel, message, username) from PRIVMSG components.

    Returns (None, None, None) if parsing fails.
    """
    if not prefix or " :" not in params:
        return None, None, None

    channel_msg = params.split(" :", 1)
    if len(channel_msg) < 2:
        return None, None, None

    channel = channel_msg[0].strip().lstrip("#").lower()
    message = channel_msg[1]
    username = prefix.split("!")[0].lstrip(":") if "!" in prefix else "unknown"
    return channel, message, username


def build_privmsg(raw: IRCMessage) -> PrivMsg | None:
    """Convert an IRCMessage representing a PRIVMSG into a PrivMsg dataclass."""
    channel, message, username = parse_privmsg_components(raw.prefix, raw.params)
    if not channel or not message or not username:
        return None
    return PrivMsg(channel=channel, author=username, message=message)
