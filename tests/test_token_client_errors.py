from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import aiohttp
import pytest

from src.auth_token.client import TokenClient, TokenOutcome
from src.errors.internal import NetworkError


class FakeResp:
    def __init__(self, status: int, payload: dict | None = None, raise_exception: Exception | None = None, json_exception: Exception | None = None):
        self.status = status
        self._payload = payload or {}
        self.raise_exception = raise_exception
        self.json_exception = json_exception

    async def __aenter__(self):
        if self.raise_exception:
            raise self.raise_exception
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    async def json(self):
        # Simulate asynchronous boundary
        await asyncio.sleep(0)
        if self.json_exception:
            raise self.json_exception
        return self._payload


class FakeSession:
    def __init__(self, validate_status: int, refresh_status: int, refresh_payload: dict | None = None, validate_exception: Exception | None = None, refresh_exception: Exception | None = None, validate_json_exception: Exception | None = None, refresh_json_exception: Exception | None = None, validate_payload: dict | None = None):
        self.validate_status = validate_status
        self.refresh_status = refresh_status
        self.refresh_payload = refresh_payload or {"access_token": "new", "expires_in": 3600, "refresh_token": "r2"}
        self.validate_payload = validate_payload or {"expires_in": 3600, "scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]}
        self.validate_exception = validate_exception
        self.refresh_exception = refresh_exception
        self.validate_json_exception = validate_json_exception
        self.refresh_json_exception = refresh_json_exception
        self.get_calls = 0
        self.post_calls = 0

    def get(self, url, headers=None, timeout=None):
        self.get_calls += 1
        if self.validate_exception:
            raise self.validate_exception
        return FakeResp(self.validate_status, self.validate_payload, None, self.validate_json_exception)

    def post(self, url, data=None, timeout=None):
        self.post_calls += 1
        if self.refresh_exception:
            raise self.refresh_exception
        return FakeResp(self.refresh_status, self.refresh_payload, None, self.refresh_json_exception)


@pytest.mark.asyncio
async def test_validate_unauthorized():
    session = FakeSession(validate_status=401, refresh_status=200)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_rate_limited():
    session = FakeSession(validate_status=200, refresh_status=429)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_refresh_success_sets_buffered_expiry():
    # expires_in=120 with buffer 300 -> safe_expires clamped to 0
    payload = {"access_token": "A", "expires_in": 120, "refresh_token": "B"}
    session = FakeSession(validate_status=200, refresh_status=200, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.REFRESHED
    assert res.expiry is not None
    assert (res.expiry - datetime.now(UTC)).total_seconds() <= 1  # clamped to near now


# Network timeouts
@pytest.mark.asyncio
async def test_validate_timeout():
    session = FakeSession(validate_status=200, refresh_status=200, validate_exception=TimeoutError())
    client = TokenClient("cid", "csec", session)
    with pytest.raises(NetworkError, match="Token validation timeout"):
        await client.validate("user", "tok")
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_timeout():
    session = FakeSession(validate_status=200, refresh_status=200, refresh_exception=TimeoutError())
    client = TokenClient("cid", "csec", session)
    with pytest.raises(NetworkError, match="Token refresh timeout"):
        await client.refresh("user", "rtok")
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_validate_client_error():
    session = FakeSession(validate_status=200, refresh_status=200, validate_exception=aiohttp.ClientError("Network error"))
    client = TokenClient("cid", "csec", session)
    with pytest.raises(NetworkError, match="Network error during validation"):
        await client.validate("user", "tok")
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_client_error():
    session = FakeSession(validate_status=200, refresh_status=200, refresh_exception=aiohttp.ClientError("Network error"))
    client = TokenClient("cid", "csec", session)
    with pytest.raises(NetworkError, match="Network error during token refresh"):
        await client.refresh("user", "rtok")
    assert session.post_calls == 1


# Rate limiting
@pytest.mark.asyncio
async def test_validate_rate_limited():
    session = FakeSession(validate_status=429, refresh_status=200)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_rate_limited_with_payload():
    payload = {"error": "rate limited"}
    session = FakeSession(validate_status=200, refresh_status=429, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


# Parsing errors
@pytest.mark.asyncio
async def test_refresh_missing_access_token():
    payload = {"expires_in": 3600, "refresh_token": "r2"}  # missing access_token
    session = FakeSession(validate_status=200, refresh_status=200, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_refresh_json_parse_error():
    session = FakeSession(validate_status=200, refresh_status=200, refresh_json_exception=ValueError("Invalid JSON"))
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_refresh_invalid_expires_in():
    payload = {"access_token": "new", "expires_in": "invalid", "refresh_token": "r2"}
    session = FakeSession(validate_status=200, refresh_status=200, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED  # TypeError during expiry calculation


@pytest.mark.asyncio
async def test_refresh_no_expires_in():
    payload = {"access_token": "new", "refresh_token": "r2"}  # no expires_in
    session = FakeSession(validate_status=200, refresh_status=200, refresh_payload=payload)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.REFRESHED
    assert res.expiry is None


# Edge cases in ensure_fresh
@pytest.mark.asyncio
async def test_ensure_fresh_skip_by_expiry():
    from datetime import timedelta
    expiry = datetime.now(UTC) + timedelta(seconds=4000)  # far in future
    session = FakeSession(validate_status=200, refresh_status=200)
    client = TokenClient("cid", "csec", session)
    res = await client.ensure_fresh("user", "atok", "rtok", expiry, force_refresh=False)
    assert res.outcome == TokenOutcome.SKIPPED
    assert session.get_calls == 0
    assert session.post_calls == 0


@pytest.mark.asyncio
async def test_ensure_fresh_force_refresh():
    session = FakeSession(validate_status=200, refresh_status=200)
    client = TokenClient("cid", "csec", session)
    res = await client.ensure_fresh("user", "atok", "rtok", None, force_refresh=True)
    assert res.outcome == TokenOutcome.REFRESHED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_ensure_fresh_no_refresh_token():
    session = FakeSession(validate_status=401, refresh_status=200)  # validation fails
    client = TokenClient("cid", "csec", session)
    res = await client.ensure_fresh("user", "atok", None, None, force_refresh=False)
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1
    assert session.post_calls == 0


@pytest.mark.asyncio
async def test_ensure_fresh_validation_succeeds_skip():
    from datetime import timedelta
    expiry = datetime.now(UTC) + timedelta(seconds=3500)  # expiring soon, triggers validation
    validate_payload = {"expires_in": 3901, "scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]}  # safe_expires = 3601, > threshold
    session = FakeSession(validate_status=200, refresh_status=200, validate_payload=validate_payload)
    client = TokenClient("cid", "csec", session)
    res = await client.ensure_fresh("user", "atok", "rtok", expiry, force_refresh=False)
    assert res.outcome == TokenOutcome.SKIPPED
    assert session.get_calls == 1
    assert session.post_calls == 0


@pytest.mark.asyncio
async def test_ensure_fresh_validation_fails_refresh():
    from datetime import timedelta
    expiry = datetime.now(UTC) + timedelta(seconds=100)  # expiring soon
    session = FakeSession(validate_status=401, refresh_status=200)  # validation fails
    client = TokenClient("cid", "csec", session)
    res = await client.ensure_fresh("user", "atok", "rtok", expiry, force_refresh=False)
    assert res.outcome == TokenOutcome.REFRESHED
    assert session.get_calls == 1
    assert session.post_calls == 1


# Unexpected exceptions
@pytest.mark.asyncio
async def test_refresh_unexpected_exception():
    session = FakeSession(validate_status=200, refresh_status=200, refresh_exception=ValueError("Unexpected"))
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_validate_unexpected_exception():
    session = FakeSession(validate_status=200, refresh_status=200, validate_exception=ValueError("Unexpected"))
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_refresh_500_error():
    session = FakeSession(validate_status=200, refresh_status=500)
    client = TokenClient("cid", "csec", session)
    res = await client.refresh("user", "rtok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.post_calls == 1


@pytest.mark.asyncio
async def test_validate_500_error():
    session = FakeSession(validate_status=500, refresh_status=200)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_validate_missing_required_scopes():
    # Scopes missing chat:read
    validate_payload = {"expires_in": 3600, "scopes": ["user:read:chat", "user:manage:chat_color"]}
    session = FakeSession(validate_status=200, refresh_status=200, validate_payload=validate_payload)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_validate_invalid_scopes_format():
    # Scopes not a list
    validate_payload = {"expires_in": 3600, "scopes": "invalid"}
    session = FakeSession(validate_status=200, refresh_status=200, validate_payload=validate_payload)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1


@pytest.mark.asyncio
async def test_validate_no_scopes_key():
    # No scopes key
    validate_payload = {"expires_in": 3600}
    session = FakeSession(validate_status=200, refresh_status=200, validate_payload=validate_payload)
    client = TokenClient("cid", "csec", session)
    res = await client.validate("user", "tok")
    assert res.outcome == TokenOutcome.FAILED
    assert session.get_calls == 1
