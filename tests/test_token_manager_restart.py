from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest

from src.auth_token.manager import TokenManager


@pytest.mark.asyncio
async def test_manager_restart_cancels_old_background(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now(UTC) + timedelta(seconds=4000)
        tm._upsert_token_info("rst", "atk", "rtk", "cid", "csec", expiry)

    # Normal start
    await tm.start()
    first = tm.background_task
    assert first is not None
    # Stop then start again; new task identity expected
    with suppress(asyncio.CancelledError):
        await tm.stop()
    await tm.start()
    second = tm.background_task
    assert second is not None
    assert first is not second
    with suppress(asyncio.CancelledError):
        await tm.stop()
