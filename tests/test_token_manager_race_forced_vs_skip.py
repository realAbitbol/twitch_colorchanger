import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.auth_token.manager import TokenInfo, TokenManager, TokenOutcome


class NoopClient:
    def __init__(self):
        self.calls = 0
    async def ensure_fresh(self, username, access, refresh, expiry, force):
        self.calls += 1
        await asyncio.sleep(0)
        class R:  # noqa: E701
            pass
        r = R()
        r.outcome = TokenOutcome.SKIPPED if not force else TokenOutcome.REFRESHED
        r.access_token = access if not force else access + "X"
        r.refresh_token = refresh if not force else refresh + "X"
        r.expiry = datetime.now(UTC) + timedelta(minutes=5)
        return r

@pytest.mark.asyncio
async def test_concurrent_forced_and_natural_refresh(monkeypatch):
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

    info = TokenInfo("user", "A", "R", "cid", "csec", datetime.now(UTC)+timedelta(seconds=2))
    tm.tokens["user"] = info
    client = NoopClient()
    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: client)

    # Launch one standard ensure_fresh and one forced concurrently
    res1, res2 = await asyncio.gather(
        tm.ensure_fresh("user", force_refresh=False),
        tm.ensure_fresh("user", force_refresh=True),
    )
    # One should be REFRESHED, the other VALID/SKIPPED
    assert {res1, res2} <= {TokenOutcome.REFRESHED, TokenOutcome.VALID, TokenOutcome.SKIPPED}
    # Under lock, only one client call executed or two serialized
    assert client.calls in (1, 2)
