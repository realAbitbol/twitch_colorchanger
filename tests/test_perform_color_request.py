import asyncio

import aiohttp
import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot
from src.color.models import ColorRequestStatus


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
    # Speed up test by making sleeps instant
    async def no_sleep(delay):
        # Intentionally empty to mock asyncio.sleep for faster tests
        pass
    monkeypatch.setattr("asyncio.sleep", no_sleep)

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
    r1 = await bot.color_changer._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r2 = await bot.color_changer._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r3 = await bot.color_changer._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")
    r4 = await bot.color_changer._perform_color_request({"user_id": "u", "color": "#123456"}, action="color_change")

    assert r1.status == ColorRequestStatus.SUCCESS
    assert r2.status == ColorRequestStatus.UNAUTHORIZED
    assert r3.status == ColorRequestStatus.HTTP_ERROR  # 429 retries, then 500
    assert r4.status == ColorRequestStatus.HTTP_ERROR

    await session.close()
    await ctx.shutdown()
