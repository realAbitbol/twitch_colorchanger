from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp
import pytest

from src.auth_token.client import TokenClient, TokenResult
from src.auth_token.manager import TokenManager, TokenOutcome
from src.config.async_persistence import flush_pending_updates, queue_user_update


class SmokeTokenClient(TokenClient):
    def __init__(self):  # type: ignore[override]
        pass

    def prime(self):
        self.refresh_calls = 0
        self.validate_calls = 0

    async def _validate_remote(self, username: str, access_token: str):  # type: ignore[override]
        self.validate_calls += 1
        # Indicate expiring soon to trigger refresh logic
        return True, datetime.now(UTC) + timedelta(seconds=5)

    async def ensure_fresh(  # type: ignore[override]
        self,
        username: str,
        access_token: str,
        refresh_token: str | None,
        expiry: datetime | None,
        force_refresh: bool = False,
    ) -> TokenResult:
        if force_refresh or (expiry and (expiry - datetime.now(UTC)).total_seconds() < 30):
            self.refresh_calls += 1
            new_expiry = datetime.now(UTC) + timedelta(seconds=3600)
            return TokenResult(TokenOutcome.REFRESHED, access_token + "Z", refresh_token, new_expiry)
        return TokenResult(TokenOutcome.VALID, access_token, refresh_token, expiry)


@pytest.mark.asyncio
async def test_end_to_end_smoke(tmp_path: Path, monkeypatch):
    async with aiohttp.ClientSession() as session:
        tm = TokenManager(session)
        tm.tokens.clear()
        # Seed a token expiring very soon
        near_expiry = datetime.now(UTC) + timedelta(seconds=2)
        await tm._upsert_token_info("smoke", "atk", "rtk", "cid", "csec", near_expiry)
        dummy = SmokeTokenClient()
        dummy.prime()
        monkeypatch.setattr(tm, "_get_client", lambda cid, _: dummy)
        await tm.start()
        # Manually drive a background iteration to avoid relying on sleep timing.
        info = tm.tokens.get("smoke")
        if info is not None:
            await tm._process_single_background("smoke", info, force_proactive=True)  # noqa: SLF001
        # Fallback: wait a short while in case background loop races in.
        for _ in range(10):
            if dummy.refresh_calls:
                break
            await asyncio.sleep(0.01)
        assert dummy.refresh_calls >= 1, "Expected at least one refresh in smoke test (manual or background)"
        # Simulate persistence of updated tokens via queue
        cfg = tmp_path / "users.json"
        await queue_user_update({"username": "smoke", "channels": ["#a"], "access_token": "a" * 20, "client_id": "b" * 10, "client_secret": "c" * 10}, str(cfg))
        await flush_pending_updates(str(cfg))
        assert cfg.exists()
        content = json.loads(cfg.read_text())
        users = content["users"] if isinstance(content, dict) and "users" in content else content
        assert any(u.get("username") == "smoke" for u in users)
        from contextlib import suppress
        with suppress(asyncio.CancelledError):
            await tm.stop()
