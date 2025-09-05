import asyncio

import pytest

from src.config.core import (
    _validate_or_invalidate_scopes as validate_scopes,  # type: ignore
)


class DummyAPI:
    def __init__(self, responses):
        self._responses = list(responses)
    async def validate_token(self, access):
        await asyncio.sleep(0)
        if self._responses:
            return self._responses.pop(0)
        return None

@pytest.mark.asyncio
async def test_retains_on_malformed_then_valid():
    user = {"username": "alice", "access_token": "A", "refresh_token": "R"}
    api = DummyAPI([{"unexpected": True}, {"scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]}])
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    kept = await validate_scopes(user, "A", "R", api, required)
    assert kept is True
    assert user.get("access_token") == "A"

@pytest.mark.asyncio
async def test_double_check_confirms_missing_and_invalidates():
    user = {"username": "bob", "access_token": "AA", "refresh_token": "RR"}
    # both validations return incomplete scopes
    api = DummyAPI([
        {"scopes": ["chat:read"]},
        {"scopes": ["chat:read"]},
    ])
    required = {"chat:read", "user:read:chat"}
    kept = await validate_scopes(user, "AA", "RR", api, required)
    assert kept is False
    assert "access_token" not in user and "refresh_token" not in user

@pytest.mark.asyncio
async def test_second_validation_recovers_scopes():
    user = {"username": "carol", "access_token": "AAA", "refresh_token": "RRR"}
    api = DummyAPI([
        {"scopes": ["chat:read"]},
        {"scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]},
    ])
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    kept = await validate_scopes(user, "AAA", "RRR", api, required)
    assert kept is True
    assert user.get("access_token") == "AAA"
