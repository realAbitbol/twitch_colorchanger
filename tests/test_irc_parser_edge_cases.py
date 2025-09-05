from __future__ import annotations

from src.irc.parser import build_privmsg, parse_irc_message


def test_parse_malformed_missing_spaces():  # type: ignore[no-untyped-def]
    raw = ":nick!user@hostPRIVMSG#chan:hello"  # missing space before command
    # Parser is simplistic; ensure it doesn't crash and returns best-effort tokens
    msg = parse_irc_message(raw)
    # Due to lack of space, prefix parsing will grab until first space (which is absent)
    assert msg.raw == raw
    # It won't detect command properly; ensure function returns object with original raw
    assert msg.command is None or isinstance(msg.command, str)


def test_parse_tags_and_params():  # type: ignore[no-untyped-def]
    raw = "@badge=1;color=red :nick!u@h PRIVMSG #room :Hello there"
    msg = parse_irc_message(raw)
    assert msg.tags.get("badge") == "1"
    assert msg.tags.get("color") == "red"
    assert msg.command == "PRIVMSG"
    priv = build_privmsg(msg)
    assert priv is not None
    assert priv.author.startswith("nick")
    assert priv.channel == "room"
    assert priv.message == "Hello there"


def test_build_privmsg_invalid_command():  # type: ignore[no-untyped-def]
    raw = ":nick!u@h PING :pong"
    msg = parse_irc_message(raw)
    assert build_privmsg(msg) is None


def test_build_privmsg_missing_params():  # type: ignore[no-untyped-def]
    raw = ":nick!u@h PRIVMSG #room"  # No trailing message params
    msg = parse_irc_message(raw)
    assert build_privmsg(msg) is None
