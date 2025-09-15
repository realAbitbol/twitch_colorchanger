import asyncio
from datetime import datetime, timedelta

import pytest

from src.auth_token.manager import TokenInfo, TokenManager


@pytest.mark.asyncio
async def test_remove_and_prune(monkeypatch):
    from src.auth_token.manager import TokenManager as _TM
    _TM._instance = None  # type: ignore[attr-defined]
    tm = object.__new__(TokenManager)  # type: ignore[call-arg]
    tm.http_session = None
    tm.tokens = {}
    tm.background_task = None
    tm.running = False
    tm._client_cache = {}
    tm._update_hooks = {}
    tm._hook_tasks = []
    tm._tokens_lock = asyncio.Lock()

    info1 = TokenInfo("u1", "a1", "r1", "cid", "csec", datetime.now()+timedelta(hours=1))
    info2 = TokenInfo("u2", "a2", "r2", "cid", "csec", datetime.now()+timedelta(hours=1))
    tm.tokens["u1"] = info1
    tm.tokens["u2"] = info2

    assert await tm.remove("u1") is True
    assert "u1" not in tm.tokens
    removed = await tm.prune({"u2"})
    assert removed == 0
    removed2 = await tm.prune(set())
    assert removed2 == 1 and not tm.tokens
