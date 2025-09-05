from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from src.token.client import TokenClient, TokenOutcome


class FakeResp:
    def __init__(self, status: int, payload: dict | None = None):
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        # Simulate asynchronous boundary
        await asyncio.sleep(0)
        return self._payload


class FakeSession:
    def __init__(self, validate_status: int, refresh_status: int, refresh_payload: dict | None = None):
        self.validate_status = validate_status
        self.refresh_status = refresh_status
        self.refresh_payload = refresh_payload or {"access_token": "new", "expires_in": 3600, "refresh_token": "r2"}
        self.get_calls = 0
        self.post_calls = 0

    def get(self, url, headers=None, timeout=None):  # type: ignore[override]
        self.get_calls += 1
        return FakeResp(self.validate_status, {"expires_in": 3600})

    def post(self, url, data=None, timeout=None):  # type: ignore[override]
        self.post_calls += 1
        return FakeResp(self.refresh_status, self.refresh_payload)


@pytest.mark.asyncio
async def test_validate_unauthorized():
    session = FakeSession(validate_status=401, refresh_status=200)
    client = TokenClient("cid", "csec", session)  # type: ignore[arg-type]
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_rate_limited():
    session = FakeSession(validate_status=200, refresh_status=429)
    client = TokenClient("cid", "csec", session)  # type: ignore[arg-type]
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_refresh_success_sets_buffered_expiry():
    # expires_in=120 with buffer 300 -> safe_expires clamped to 0
    payload = {"access_token": "A", "expires_in": 120, "refresh_token": "B"}
    session = FakeSession(validate_status=200, refresh_status=200, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)  # type: ignore[arg-type]
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.REFRESHED
    assert res.expiry is not None
    assert (res.expiry - datetime.now()).total_seconds() <= 1  # clamped to near now
