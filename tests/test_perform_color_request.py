import asyncio
import types
import pytest
from src.bot.core import TwitchColorBot
from src.color.models import ColorRequestStatus
from src.application_context import ApplicationContext
import aiohttp

class FakeAPI:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []
        self._idx = 0
    async def request(self, method, endpoint, access_token=None, client_id=None, params=None):  # noqa: D401
        self.calls.append((method, endpoint, params))
        await asyncio.sleep(0)
        if self._idx >= len(self._responses):
            return {}, 500, {}
        r = self._responses[self._idx]
        self._idx += 1
        return r

@pytest.mark.asyncio
async def test_perform_color_request_status_mapping(monkeypatch):
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
    # Bypass rate limiter wait
    async def _no_wait(*a, **k):
        await asyncio.sleep(0)
    monkeypatch.setattr(bot.rate_limiter, "wait_if_needed", _no_wait)
    monkeypatch.setattr(bot.rate_limiter, "update_from_headers", lambda *a, **k: None)

    # Inject fake api with sequence of responses
    responses = [
        ({}, 204, {}),  # success
        ({"message": "Unauthorized"}, 401, {}),
        ({}, 429, {}),
        ({"error": "boom"}, 500, {}),
    ]
    fake_api = FakeAPI(responses)
    bot.api = fake_api  # type: ignore

    # Call private method sequentially
    r1 = await bot._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r2 = await bot._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r3 = await bot._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r4 = await bot._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")

    assert r1.status == ColorRequestStatus.SUCCESS
    assert r2.status == ColorRequestStatus.UNAUTHORIZED
    assert r3.status == ColorRequestStatus.RATE_LIMIT
    assert r4.status == ColorRequestStatus.HTTP_ERROR

    await session.close()
    await ctx.shutdown()
