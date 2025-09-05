from __future__ import annotations

from datetime import datetime, timedelta

import aiohttp
import pytest

from src.token.client import TokenClient, TokenResult
from src.token.manager import TokenManager, TokenOutcome, TokenState

# --- Dummy clients for targeted edge behaviors ---

class UnknownExpiryClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self):  # symmetry with others
        self.calls: list[tuple[str, bool]] = []  # (username, forced)

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        self.calls.append((username, force_refresh))
        # Always return a successful outcome but without an expiry so manager keeps treating unknown.
        return TokenResult(TokenOutcome.VALID, access_token, refresh_token, None)


class RateLimitFailClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self):
        self.calls: int = 0

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        self.calls += 1
        # Simulate failed refresh (e.g. rate limit) -> FAILED outcome
        return TokenResult(TokenOutcome.FAILED, None, None, expiry)


class ProactiveDriftClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self):
        self.refresh_calls = 0

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        self.refresh_calls += 1
        new_expiry = datetime.now() + timedelta(seconds=4000)
        return TokenResult(TokenOutcome.REFRESHED, access_token + "N", refresh_token, new_expiry)

    async def _validate_remote(self, username: str, access_token: str):  # type: ignore[override]
        # Return valid with a distant expiry so validation alone does not trigger refresh.
        return True, datetime.now() + timedelta(seconds=4000)


# --- Tests ---


@pytest.mark.asyncio
async def test_unknown_expiry_forced_refresh_attempts_capped(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        # Insert token with unknown expiry
        tm._upsert_token_info("ux", "acc", "ref", "cid", "csec", None)
        dummy = UnknownExpiryClient()
        dummy.prime()
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        info = tm.get_info("ux")
        # Invoke unknown expiry handler multiple times
        for _ in range(5):
            await tm._handle_unknown_expiry("ux")
        assert info is not None
        # Forced attempts capped at 3
        assert info.forced_unknown_attempts == 3
        # Expect at least one forced refresh (True flag present) after first non-forced call
        forced_flags = [forced for _u, forced in dummy.calls]
        assert forced_flags.count(True) >= 1


@pytest.mark.asyncio
async def test_failed_refresh_sets_expired(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() + timedelta(seconds=100)
        tm._upsert_token_info("rl", "acc2", "ref2", "cid", "csec", expiry)
        dummy = RateLimitFailClient()
        dummy.prime()
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        outcome = await tm.ensure_fresh("rl", force_refresh=True)
        info = tm.get_info("rl")
        assert outcome == TokenOutcome.FAILED
        assert info is not None and info.state == TokenState.EXPIRED


@pytest.mark.asyncio
async def test_proactive_drift_doubles_threshold_triggers_refresh(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
    remaining_seconds = 5000  # Between 3600 and 7200
    expiry = datetime.now() + timedelta(seconds=remaining_seconds)
    tm._upsert_token_info("pd", "acc3", "ref3", "cid", "csec", expiry)
    dummy = ProactiveDriftClient()
    dummy.prime()
    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
    info = tm.get_info("pd")
    assert info is not None
    info.last_validation = datetime.now().timestamp()
    await tm._process_single_background("pd", info, force_proactive=False)  # type: ignore[arg-type]
    assert dummy.refresh_calls == 0
    await tm._process_single_background("pd", info, force_proactive=True)  # type: ignore[arg-type]
    assert dummy.refresh_calls == 1
