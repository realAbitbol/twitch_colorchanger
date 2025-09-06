from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import aiohttp

from src.token.manager import TokenManager, TokenInfo, TokenOutcome
from src.constants import TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL


def _setup_manager(session: aiohttp.ClientSession) -> TokenManager:
    tm = TokenManager(session)
    tm.tokens.clear()
    tm._keepalive_callbacks.clear()  # type: ignore[attr-defined]
    return tm


def test_keepalive_callback_fires_on_periodic_validation():  # type: ignore[no-untyped-def]
    async def run():
        async with aiohttp.ClientSession() as session:
            tm = _setup_manager(session)
            username = "user1"
            now = time.time()
            info = TokenInfo(
                username=username,
                access_token="atk",
                refresh_token="rtk",
                client_id="cid",
                client_secret="csec",
                expiry=datetime.now(UTC) + timedelta(hours=2),
            )
            # Force last validation far enough in past to trigger periodic branch
            info.last_validation = now - TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL - 5
            tm.tokens[username] = info

            fired = asyncio.Event()

            async def keepalive_cb():  # noqa: D401
                fired.set(); await asyncio.sleep(0)

            tm.register_keepalive_callback(username, keepalive_cb)

            # Monkeypatch validate to always succeed without network
            async def fake_validate(user: str) -> TokenOutcome:  # noqa: D401
                info.last_validation = time.time(); await asyncio.sleep(0)
                return TokenOutcome.VALID

            tm.validate = fake_validate  # type: ignore[assignment]

            # Call internal method to simulate background loop logic
            remaining = 4000.0
            await tm._maybe_periodic_or_unknown_resolution(username, info, remaining)  # type: ignore[attr-defined]

            # Allow callback task to run
            await asyncio.wait_for(fired.wait(), timeout=1.0)

    asyncio.run(run())


def test_keepalive_callback_not_fired_when_recent():  # type: ignore[no-untyped-def]
    async def run():
        async with aiohttp.ClientSession() as session:
            tm = _setup_manager(session)
            username = "user2"
            info = TokenInfo(
                username=username,
                access_token="atk",
                refresh_token="rtk",
                client_id="cid",
                client_secret="csec",
                expiry=datetime.now(UTC) + timedelta(hours=2),
            )
            # Last validation very recent -> should skip periodic path
            info.last_validation = time.time() - 5
            tm.tokens[username] = info

            fired = asyncio.Event()

            async def keepalive_cb():  # noqa: D401
                fired.set(); await asyncio.sleep(0)

            tm.register_keepalive_callback(username, keepalive_cb)

            async def fake_validate(user: str) -> TokenOutcome:  # noqa: D401
                info.last_validation = time.time(); await asyncio.sleep(0)
                return TokenOutcome.VALID

            tm.validate = fake_validate  # type: ignore[assignment]

            remaining = 4000.0
            await tm._maybe_periodic_or_unknown_resolution(username, info, remaining)  # type: ignore[attr-defined]

            # Give loop a moment; it should NOT fire
            try:
                await asyncio.wait_for(fired.wait(), timeout=0.2)
                raised = True
            except TimeoutError:
                raised = False
            # fired should remain unset
            if raised:
                raise AssertionError("Keepalive callback fired unexpectedly for recent validation")

    asyncio.run(run())
