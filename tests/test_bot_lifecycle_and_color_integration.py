from __future__ import annotations

import asyncio

import aiohttp
import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot
from src.color.models import ColorRequestResult, ColorRequestStatus  # noqa: F401
from src.color.service import ColorChangeService  # noqa: F401


class DummyBackend:
    def __init__(self) -> None:  # noqa: D401
        self.connected = False
        self.disconnected = False
        self._message_handler = None
        self._color_handler = None

    async def connect(  # noqa: D401
        self,
        token: str,
        nick: str,
        channel: str,
        user_id: str | None,
        client_id: str,
        client_secret: str,
    ) -> bool:
        self.connected = True
        # tiny await to satisfy async usage
        await asyncio.sleep(0)
        return True

    async def join_channel(self, channel: str) -> None:  # noqa: D401
        await asyncio.sleep(0)

    async def listen(self) -> None:  # noqa: D401
        await asyncio.sleep(0)

    async def disconnect(self) -> None:  # noqa: D401
        self.disconnected = True
        await asyncio.sleep(0)

    def set_message_handler(self, fn):  # noqa: D401, ANN001
        self._message_handler = fn


@pytest.mark.asyncio()
async def test_bot_start_and_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = await ApplicationContext.create()
    await ctx.start()
    session = aiohttp.ClientSession()
    bot = TwitchColorBot(
        context=ctx,
        token="tok",  # noqa: S106
        refresh_token="rtok",  # noqa: S106
        client_id="cid",
        client_secret="csec",  # noqa: S106
        nick="nick",
        channels=["#main", "#extra"],
        http_session=session,
    )
    dummy = DummyBackend()
    monkeypatch.setattr(
        "src.bot.core.EventSubChatBackend", lambda http_session=None: dummy  # noqa: ARG005
    )

    async def _fake_init_connection():  # noqa: D401
        bot.chat_backend = dummy
        dummy.connected = True
        await asyncio.sleep(0)
        return True

    async def _fake_run_loop():  # noqa: D401
        # Simulate a trivial listen task
        await asyncio.sleep(0)
        return None

    async def _fake_user_info():  # noqa: D401
        await asyncio.sleep(0)
        return {"id": "123"}

    async def _fake_current_color():  # noqa: D401
        await asyncio.sleep(0)
        return "blue"

    # Patch internals & external calls
    monkeypatch.setattr(bot, "_initialize_connection", _fake_init_connection)
    monkeypatch.setattr(bot, "_run_chat_loop", _fake_run_loop)
    monkeypatch.setattr(bot, "_get_user_info", _fake_user_info)
    monkeypatch.setattr(bot, "_get_current_color", _fake_current_color)
    # Token manager ensure_fresh
    if ctx.token_manager:
        monkeypatch.setattr(
            ctx.token_manager,
            "ensure_fresh",
            lambda *a, **k: asyncio.sleep(0),
        )

    await bot.start()
    # Assertions after start
    if not dummy.connected:
        raise AssertionError("Backend not connected during start")
    if not bot.running:
        raise AssertionError("Bot.running not True after start")
    # Stop
    await bot.stop()
    if bot.running:
        raise AssertionError("Bot.running not False after stop")
    if not dummy.disconnected:
        raise AssertionError("Backend not disconnected on stop")
    # Cleanup
    await session.close()
    if ctx.session and not ctx.session.closed:
        await ctx.session.close()


# Color change tests moved to dedicated file `test_color_change_service.py` for clarity.
