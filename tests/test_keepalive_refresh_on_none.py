from __future__ import annotations

import asyncio
import aiohttp
import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot


class FakeAPI:
    def __init__(self, color: str | None):
        self.color = color
        self.calls = []

    async def request(self, method, endpoint, access_token=None, client_id=None, params=None):  # noqa: D401, ANN001
        self.calls.append((method, endpoint, params))
        await asyncio.sleep(0)
        if method == "GET" and endpoint.endswith("chat/color"):
            if self.color:
                return {"data": [{"color": self.color}]}, 200, {}
            return {"data": []}, 200, {}
        return {}, 200, {}


@pytest.mark.asyncio
async def test_keepalive_no_color_forces_token_refresh(monkeypatch, caplog):
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
    # Make idle exceed threshold so keepalive runs
    bot._last_activity_ts -= (bot._keepalive_recent_activity + 1)

    # Fake API returns no color on GET
    bot.api = FakeAPI(color=None)  # type: ignore

    # Capture ensure_fresh(force=True) via bot helper
    called = {"force": False}

    async def _ensure_fresh(username: str, *, force_refresh: bool = False):  # noqa: ANN001
        called["force"] = force_refresh
        await asyncio.sleep(0)
        return None

    if ctx.token_manager is None:
        raise AssertionError("Token manager missing from context")

    monkeypatch.setattr(ctx.token_manager, "ensure_fresh", _ensure_fresh)

    caplog.set_level(20)

    await bot._maybe_get_color_keepalive()

    # Assert we logged the none event and requested a forced refresh
    msgs = [r.message for r in caplog.records]
    assert any("🫧 Keepalive color GET returned no color" in m for m in msgs)
    assert called["force"] is True

    await session.close()
    if ctx.session and not ctx.session.closed:
        await ctx.session.close()
