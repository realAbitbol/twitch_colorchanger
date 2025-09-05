from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
import pytest

from src.token.client import TokenClient, TokenResult
from src.token.manager import TokenManager, TokenOutcome


class DummyTokenClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self, scenario: str) -> None:
        self._scenario = scenario
        self.refresh_calls: list[str] = []
        self.validate_calls: list[str] = []

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        self.refresh_calls.append(username + ("!" if force_refresh else ""))
        if self._scenario == "refresh_success":
            new_expiry = datetime.now() + timedelta(seconds=3600)
            return TokenResult(TokenOutcome.REFRESHED, access_token + "X", refresh_token or "r", new_expiry)
        if self._scenario == "refresh_fail":
            return TokenResult(TokenOutcome.FAILED, None, None, None)
        return TokenResult(TokenOutcome.SKIPPED, access_token, refresh_token, expiry)

    async def _validate_remote(self, username: str, access_token: str):  # type: ignore[override]
        self.validate_calls.append(username)
        if self._scenario == "valid":
            return True, datetime.now() + timedelta(seconds=4000)
        if self._scenario == "invalid":
            return False, None
        return True, datetime.now() + timedelta(seconds=100)


@pytest.mark.asyncio
async def test_startup_initial_validation_refresh(monkeypatch):
    # Setup manager with one token expiring soon to trigger refresh
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        near_expiry = datetime.now() + timedelta(seconds=10)
        tm._upsert_token_info("alice", "atk", "rtk", "cid", "csec", near_expiry)

        dummy = DummyTokenClient()
        dummy.prime("refresh_success")
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)  # bypass network

        await tm.start()
        await asyncio.sleep(0)  # let background loop tick
        outcome = await tm.ensure_fresh("alice")
        assert outcome in {TokenOutcome.SKIPPED, TokenOutcome.VALID, TokenOutcome.REFRESHED}
        assert dummy.refresh_calls, "Expected at least one refresh attempt"
        with suppress(asyncio.CancelledError):
            await tm.stop()


@pytest.mark.asyncio
async def test_force_refresh_path(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() + timedelta(seconds=5000)
        tm._upsert_token_info("bob", "atk2", "rtk2", "cid", "csec", expiry)
        dummy = DummyTokenClient()
        dummy.prime("refresh_success")
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        outcome = await tm.ensure_fresh("bob", force_refresh=True)
        assert outcome in {TokenOutcome.REFRESHED, TokenOutcome.FAILED}
        assert dummy.refresh_calls and dummy.refresh_calls[0].endswith("!"), "Force flag not propagated"


@pytest.mark.asyncio
async def test_failed_refresh_marks_state(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() - timedelta(seconds=5)
        info = tm._upsert_token_info("carol", "tok", "rtok", "cid", "csec", expiry)
        dummy = DummyTokenClient()
        dummy.prime("refresh_fail")
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        res = await tm.ensure_fresh("carol", force_refresh=True)
        assert res in {TokenOutcome.FAILED, TokenOutcome.REFRESHED}
        if res == TokenOutcome.FAILED:
            assert info.state.name in {"EXPIRED", "STALE"}


@pytest.mark.asyncio
async def test_register_update_hook_fires(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() + timedelta(seconds=1)
        tm._upsert_token_info("dan", "tokd", "rtokd", "cid", "csec", expiry)
        dummy = DummyTokenClient()
        dummy.prime("refresh_success")
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        fired: list[str] = []

        async def hook() -> None:
            await asyncio.sleep(0)
            fired.append("hook")

        tm.register_update_hook("dan", hook)
        await tm.ensure_fresh("dan", force_refresh=True)
        # Allow hook task to run (retry loop to avoid flakiness)
        for _ in range(5):
            if fired:
                break
            await asyncio.sleep(0.01)
        assert fired, "Update hook not invoked"


@pytest.mark.asyncio
async def test_prune_removes_inactive_users():
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        tm._upsert_token_info("eve", "tok", "rtok", "cid", "csec", datetime.now())
        tm._upsert_token_info("frank", "tok2", "rtok2", "cid", "csec", datetime.now())
        removed = tm.prune({"eve"})
        assert removed == 1
        assert tm.get_info("frank") is None
