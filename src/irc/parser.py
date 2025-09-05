"""IRC message parsing utilities (packaged)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IRCMessage:
    raw: str
    prefix: str | None
    command: str | None
    params: str
    tags: dict[str, str]


def parse_irc_message(raw_line: str) -> IRCMessage:
    tags: dict[str, str] = {}
    prefix: str | None = None
    params = ""
    command: str | None = None

    original = raw_line

    if raw_line.startswith("@"):
        tags_part, raw_line = raw_line.split(" ", 1)
        tags = _parse_tags(tags_part[1:])

    if raw_line.startswith(":"):
        # Defensive: malformed lines may omit space after prefix; guard split
        remainder = raw_line[1:]
        if " " in remainder:
            prefix, raw_line = remainder.split(" ", 1)
        else:  # malformed; treat whole remainder as prefix and leave rest empty
            prefix = remainder
            raw_line = ""

    if " :" in raw_line:
        raw_line, params = raw_line.split(" :", 1)

    parts = raw_line.split()
    if parts:
        command = parts[0]
        if len(parts) > 1:
            middle = parts[1:]
            params = (" ".join(middle) + (f" {params}" if params else "")).strip()

    return IRCMessage(
        raw=original, prefix=prefix, command=command, params=params, tags=tags
    )


def _parse_tags(raw_tags: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for tag in raw_tags.split(";"):
        if "=" in tag:
            k, v = tag.split("=", 1)
        else:
            k, v = tag, ""
        tags[k] = v
    return tags


@dataclass
class PrivMsg:
    author: str
    channel: str
    message: str
    tags: dict[str, str]


def build_privmsg(parsed: IRCMessage) -> PrivMsg | None:
    if parsed.command != "PRIVMSG":
        return None
    params = parsed.params.split(" ", 1)
    if len(params) < 2:
        return None
    channel_token, message = params
    channel = channel_token.lstrip("#").lower()
    # Author from prefix (nick!user@host)
    author = (parsed.prefix or "?").split("!", 1)[0]
    return PrivMsg(author=author, channel=channel, message=message, tags=parsed.tags)
