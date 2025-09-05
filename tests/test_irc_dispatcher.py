import asyncio
from typing import Any

import pytest

from src.irc.async_irc import AsyncTwitchIRC
from src.irc.dispatcher import IRCDispatcher


class DummyIRC(AsyncTwitchIRC):
    def __init__(self) -> None:  # keep base init
        super().__init__()
        self.username = "tester"
        self.sent: list[str] = []

    async def _send_line(self, message: str) -> None:  # capture instead of network
        self.sent.append(message)


@pytest.mark.asyncio
async def test_ping_pong_response():
    client = DummyIRC()
    disp = IRCDispatcher(client)
    buf = await disp.process_incoming_data("", "PING :tmi.twitch.tv\r\n")
    assert buf == ""
    assert "PONG :tmi.twitch.tv" in client.sent


@pytest.mark.asyncio
async def test_privmsg_parsing_invokes_message_handler():
    client = DummyIRC()
    events: list[tuple[str, str, str]] = []

    async def handler(user: str, channel: str, message: str) -> None:
        events.append((user, channel, message))
        await asyncio.sleep(0)

    client.username = "tester"
    client.set_message_handler(handler)
    disp = IRCDispatcher(client)
    raw = (
        ":tester!tester@test PRIVMSG #mychan :hello world\r\n"
    )  # bot message (will be logged as self_message)
    await disp.process_incoming_data("", raw)
    assert events == [("tester", "mychan", "hello world")]


@pytest.mark.asyncio
async def test_privmsg_triggers_color_change_handler_only_for_bang():
    client = DummyIRC()
    invoked: list[str] = []

    async def color_handler(user: str, channel: str, message: str) -> None:
        invoked.append(message)
        await asyncio.sleep(0)

    client.username = "tester"
    client.set_color_change_handler(color_handler)
    disp = IRCDispatcher(client)
    # Non-command
    await disp.process_incoming_data(
        "", ":tester!u@test PRIVMSG #c :just chatting\r\n"
    )
    # Command style
    await disp.process_incoming_data(
        "", ":tester!u@test PRIVMSG #c :!changecolor\r\n"
    )
    assert invoked == ["!changecolor"]


@pytest.mark.asyncio
async def test_message_handler_exception_logged_not_propagated(monkeypatch):
    client = DummyIRC()
    seen: list[str] = []

    async def bad_handler(user: str, channel: str, message: str) -> None:  # noqa: ARG001
        raise RuntimeError("boom")

    client.username = "tester"
    client.set_message_handler(bad_handler)
    disp = IRCDispatcher(client)

    # Monkeypatch logger to capture event names for assertion
    from src.logs.logger import logger as bot_logger

    original_log_event = bot_logger.log_event

    def capture(domain: str, action: str, **kwargs: Any) -> None:  # noqa: D401
        if action == "message_handler_error":
            seen.append(action)
        original_log_event(domain, action, **kwargs)

    monkeypatch.setattr(bot_logger, "log_event", capture)

    await disp.process_incoming_data(
        "", ":tester!u@test PRIVMSG #room :hello there\r\n"
    )
    assert seen == ["message_handler_error"]
