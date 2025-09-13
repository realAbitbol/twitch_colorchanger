from __future__ import annotations

import asyncio

import aiohttp
import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def request(self, method, endpoint, access_token=None, client_id=None, params=None):  # noqa: D401, ANN001
        self.calls.append((method, endpoint, params))
        await asyncio.sleep(0)
        return {}, 200, {}


@pytest.mark.asyncio
async def test_ccc_invalid_argument_logs_info(monkeypatch, caplog):
    ctx = await ApplicationContext.create()
    session = aiohttp.ClientSession()
    bot = TwitchColorBot(
        context=ctx,
        token="tok",  # noqa: S106
        refresh_token="rtok",  # noqa: S106
        client_id="cid",
        client_secret="csec",  # noqa: S106
        nick="nick",
        channels=["#main"],
        http_session=session,
    )
    fake_api = FakeAPI()
    bot.api = fake_api  # type: ignore

    caplog.set_level(20)

    await bot.handle_message("nick", "main", "ccc nonsense")

    # No PUT should be made
    assert not any(c[0] == "PUT" and c[1].endswith("chat/color") for c in fake_api.calls)
    # Info event should be emitted
    msgs = [r.message for r in caplog.records]
    assert any("ℹ️ Ignoring invalid ccc argument" in m for m in msgs)

    await session.close()
    if ctx.session and not ctx.session.closed:
        await ctx.session.close()
