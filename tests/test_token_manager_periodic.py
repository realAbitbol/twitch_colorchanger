from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
import pytest

from src.token.client import TokenClient, TokenResult
from src.token.manager import TokenManager, TokenOutcome


class PeriodicDummyClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self, *, validate_outcome: bool, refresh_on_force: bool = True) -> None:
        self.validate_outcome = validate_outcome
        self.refresh_on_force = refresh_on_force
        self.validate_calls = 0
        self.refresh_calls = 0

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        # Only simulate real refresh when forced and configured
        if force_refresh and self.refresh_on_force and refresh_token:
            self.refresh_calls += 1
            new_expiry = datetime.now() + timedelta(seconds=4000)
            return TokenResult(TokenOutcome.REFRESHED, access_token + "R", refresh_token, new_expiry)
        return TokenResult(TokenOutcome.VALID, access_token, refresh_token, expiry)

    async def _validate_remote(self, username: str, access_token: str):  # type: ignore[override]
        self.validate_calls += 1
        if self.validate_outcome:
            return True, datetime.now() + timedelta(seconds=2000)
        return False, None


@pytest.mark.asyncio
async def test_periodic_validation_triggers_refresh(monkeypatch):
    # Override periodic interval and base sleep to run fast
    monkeypatch.setenv("TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL", "1")
    monkeypatch.setenv("TOKEN_MANAGER_VALIDATION_MIN_INTERVAL", "0")
    monkeypatch.setenv("TOKEN_MANAGER_BACKGROUND_BASE_SLEEP", "0")

    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        # Token with known expiry far enough to skip proactive immediate refresh
        expiry = datetime.now() + timedelta(seconds=5000)
        tm._upsert_token_info("puser", "acc", "ref", "cid", "csec", expiry)

        dummy = PeriodicDummyClient()
        dummy.prime(validate_outcome=False, refresh_on_force=True)
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)

        await tm.start()
        # Allow background loop + periodic validation cycle (a few ticks)
        for _ in range(10):
            if dummy.refresh_calls:
                break
            await asyncio.sleep(0.01)
        assert dummy.validate_calls >= 1, "Expected periodic validation calls"
        assert dummy.refresh_calls >= 1, "Expected forced refresh after failed validation"
        with suppress(asyncio.CancelledError):
            await tm.stop()


@pytest.mark.asyncio
async def test_periodic_validation_success_no_refresh(monkeypatch):
    monkeypatch.setenv("TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL", "1")
    monkeypatch.setenv("TOKEN_MANAGER_VALIDATION_MIN_INTERVAL", "0")
    monkeypatch.setenv("TOKEN_MANAGER_BACKGROUND_BASE_SLEEP", "0")

    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() + timedelta(seconds=5000)
        tm._upsert_token_info("puser2", "acc2", "ref2", "cid", "csec", expiry)

        dummy = PeriodicDummyClient()
        dummy.prime(validate_outcome=True)
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)

        await tm.start()
        for _ in range(10):
            if dummy.validate_calls:
                break
            await asyncio.sleep(0.01)
        # Successful validation should not trigger refresh
        assert dummy.validate_calls >= 1
        assert dummy.refresh_calls == 0
        with suppress(asyncio.CancelledError):
            await tm.stop()
