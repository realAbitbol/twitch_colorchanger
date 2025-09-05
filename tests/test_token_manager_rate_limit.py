from __future__ import annotations

from datetime import datetime, timedelta

import aiohttp
import pytest

from src.token.client import TokenClient, TokenResult
from src.token.client import TokenOutcome as ClientOutcome
from src.token.manager import TokenManager


class RateLimitedValidateClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self):
        self.validate_calls = 0
        self.refresh_calls = 0

    async def _validate_remote(self, username: str, access_token: str):  # type: ignore[override]
        self.validate_calls += 1
        # Simulate rate limited -> manager treat as failed validation -> forced refresh path
        return False, None

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        if force_refresh:
            self.refresh_calls += 1
            new_expiry = datetime.now() + timedelta(seconds=3600)
            return TokenResult(ClientOutcome.REFRESHED, access_token + "N", refresh_token, new_expiry)
        return TokenResult(ClientOutcome.VALID, access_token, refresh_token, expiry)


@pytest.mark.asyncio
async def test_rate_limited_validation_leads_to_forced_refresh(monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        expiry = datetime.now() + timedelta(seconds=5000)
        tm._upsert_token_info("rluser", "acc", "ref", "cid", "csec", expiry)
        dummy = RateLimitedValidateClient()
        dummy.prime()
        monkeypatch.setattr(tm, "_get_client", lambda cid, cs: dummy)
        # Force immediate periodic check by manipulating last_validation
        info = tm.get_info("rluser")
        assert info is not None
        info.last_validation = 0  # ensure periodic interval exceeded
        await tm._process_single_background("rluser", info)
        assert dummy.validate_calls >= 1
        assert dummy.refresh_calls >= 1, "Expected forced refresh after failed validation classification"
