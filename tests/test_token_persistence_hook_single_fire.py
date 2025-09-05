import asyncio
from datetime import datetime, timedelta

import pytest

from src.token.manager import TokenInfo, TokenManager, TokenOutcome


class DummyClient:
    def __init__(self, new_access: str, new_refresh: str):
        self.new_access = new_access
        self.new_refresh = new_refresh
        self.calls = 0
    async def ensure_fresh(self, username, access, refresh, expiry, force):
        self.calls += 1
        await asyncio.sleep(0)
        class R:  # simple namespace
            pass
        r = R()
        r.outcome = TokenOutcome.REFRESHED
        r.access_token = self.new_access
        r.refresh_token = self.new_refresh
        r.expiry = datetime.now() + timedelta(hours=1)
        return r

@pytest.mark.asyncio
async def test_single_update_hook_invocation(monkeypatch):
    # Ensure clean singleton state
    from src.token.manager import TokenManager as _TM  # local alias
    _TM._instance = None  # type: ignore[attr-defined]
    # Bypass custom __new__ (needs http_session) by using object.__new__
    tm = object.__new__(TokenManager)  # type: ignore[call-arg]
    # Bypass singleton init guard by directly setting attributes
    tm.http_session = None  # not used
    tm.tokens = {}
    tm.background_task = None
    tm.running = False
    from src.logs.logger import logger
    tm.logger = logger
    tm._client_cache = {}
    tm._update_hooks = {}
    tm._hook_tasks = []

    info = TokenInfo(
        username="u",
        access_token="oldA",
        refresh_token="oldR",
        client_id="cid",
        client_secret="csec",
        expiry=datetime.now() + timedelta(seconds=10),
    )
    tm.tokens["u"] = info
    dummy = DummyClient("newA", "newR")
    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)

    hook_calls = []
    async def hook():
        hook_calls.append(1)
        await asyncio.sleep(0)
    tm.register_update_hook("u", hook)

    outcome = await tm.ensure_fresh("u", force_refresh=True)
    assert outcome == TokenOutcome.REFRESHED
    # Allow hook task to run
    await asyncio.sleep(0)
    assert hook_calls == [1], f"Expected exactly one hook call, got {len(hook_calls)}"
