import asyncio

import aiohttp
import pytest

from src.auth_token.manager import TokenInfo, TokenManager, TokenOutcome, TokenResult
from src.chat.eventsub_backend import EventSubChatBackend


class DummyClient:
    def __init__(self):
        self.calls: list[str] = []

    async def ensure_fresh(self, username: str, access_token: str, refresh_token: str | None, expiry, force_refresh: bool) -> TokenResult:  # noqa: D401,E501
        self.calls.append("refresh")
        await asyncio.sleep(0)  # satisfy async usage
        return TokenResult(
            TokenOutcome.REFRESHED, f"new-{access_token}", refresh_token, expiry
        )


@pytest.mark.asyncio
async def test_eventsub_token_propagation(monkeypatch):
    session = aiohttp.ClientSession()
    tm = TokenManager(session)
    # Insert token info
    ti = TokenInfo(
        username="user",
        access_token="tok1",  # noqa: S106
        refresh_token="rtok",  # noqa: S106
        client_id="cid",
        client_secret="csec",  # noqa: S106
        expiry=None,
    )
    tm.tokens["user"] = ti
    backend = EventSubChatBackend()
    backend._username = "user"  # normally set during connect
    backend.update_access_token("tok1")
    tm.register_eventsub_backend("user", backend)

    dummy = DummyClient()
    # Force internal call path for refresh (bypassing scheduling logic)
    result, changed = await tm._refresh_with_lock(dummy, ti, "user", True)
    # Allow scheduled hook task to run
    await asyncio.sleep(0)
    assert result.outcome == TokenOutcome.REFRESHED
    assert changed is True
    # Hook should have updated backend._token
    assert backend._token == "new-tok1"  # noqa: S105

    # Simulate token invalid flag then another propagation to test recovery log
    backend._token_invalid_flag = True
    result2, changed2 = await tm._refresh_with_lock(dummy, ti, "user", True)
    await asyncio.sleep(0)
    assert result2.outcome == TokenOutcome.REFRESHED
    assert changed2 is True
    assert backend._token_invalid_flag is False

    await session.close()
