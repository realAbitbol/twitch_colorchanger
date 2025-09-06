from __future__ import annotations

import asyncio
import aiohttp
import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot
from src.logs.logger import logger as global_logger


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def request(self, method, endpoint, access_token=None, client_id=None, params=None):  # noqa: D401, ANN001
        self.calls.append((method, endpoint, params))
        await asyncio.sleep(0)
        # Simulate what would happen; but for blocked case we should not see PUT
        return {}, 200, {}


@pytest.mark.asyncio
async def test_ccc_hex_blocked_when_nonprime(monkeypatch):
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
        is_prime_or_turbo=False,
    )
    fake_api = FakeAPI()
    bot.api = fake_api  # type: ignore

    records: list[tuple[str, str, dict]] = []

    def _capture(domain: str, action: str, *args, **kwargs):  # noqa: ANN001
        records.append((domain, action, kwargs))

    monkeypatch.setattr(global_logger, "log_event", _capture)

    # Even if auto is disabled or enabled, hex via ccc should be blocked for non-prime
    bot.enabled = False
    await bot.handle_irc_message("nick", "main", "ccc #abcdef")
    bot.enabled = True
    await bot.handle_irc_message("nick", "main", "ccc ABCDEF")

    # No PUT chat/color should be issued
    assert not any(c[0] == "PUT" and c[1].endswith("chat/color") for c in fake_api.calls)
    # Log event should indicate ignore
    assert any(d == "bot" and a == "ccc_hex_ignored_nonprime" for d, a, _ in records)

    await session.close()
    if ctx._maintenance_task:  # type: ignore[attr-defined]
        ctx._maintenance_task.cancel()  # type: ignore[attr-defined]
    if ctx.session and not ctx.session.closed:
        await ctx.session.close()
