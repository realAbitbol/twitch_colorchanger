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
        # Simulate success 204 for PUT chat/color
        self.calls.append((method, endpoint, params))
        await asyncio.sleep(0)
        if method == "PUT" and endpoint.endswith("chat/color"):
            return {}, 204, {}
        return {}, 200, {}


@pytest.mark.asyncio
async def test_ccc_hex_and_preset_work_even_when_disabled(monkeypatch):
    ctx = await ApplicationContext.create()
    session = aiohttp.ClientSession()
    bot = TwitchColorBot(
        context=ctx,
        token="tok",
        refresh_token="rtok",
        client_id="cid",
        client_secret="csec",
        nick="nick",
        channels=["#main"],
        http_session=session,
    )
    # Disable auto color
    bot.enabled = False
    # Inject fake API and bypass rate limiter
    fake_api = FakeAPI()
    bot.api = fake_api  # type: ignore

    async def _no_wait(*a, **k):
        await asyncio.sleep(0)

    monkeypatch.setattr(bot.rate_limiter, "wait_if_needed", _no_wait)
    monkeypatch.setattr(bot.rate_limiter, "update_from_headers", lambda *a, **k: None)

    # Simulate receiving a command message from self
    await bot.handle_message("nick", "main", "ccc #a1b2c3")
    await bot.handle_message("nick", "main", "CCC red")
    await bot.handle_message("nick", "main", "ccc ABC")  # 3-digit hex

    # We expect 3 PUT calls for color changes
    put_calls = [c for c in fake_api.calls if c[0] == "PUT" and c[1].endswith("chat/color")]
    assert len(put_calls) == 3
    # First should be #a1b2c3
    assert put_calls[0][2]["color"] == "#a1b2c3"
    # Second preset should be normalized to lowercase 'red'
    assert put_calls[1][2]["color"] == "red"
    # Third expanded #aabbcc
    assert put_calls[2][2]["color"] == "#aabbcc"

    # Cleanup similar to other tests to avoid long-sleep cancellation
    await session.close()
    if ctx._maintenance_task:  # type: ignore[attr-defined]
        ctx._maintenance_task.cancel()  # type: ignore[attr-defined]
    if ctx.session and not ctx.session.closed:
        await ctx.session.close()
