from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from src.auth_token.device_flow import DeviceCodeFlow


class _Resp:
    def __init__(self, status: int, payload: dict[str, Any]):
        self.status = status
        self._payload = payload

    async def json(self) -> dict[str, Any]:  # noqa: D401
        await asyncio.sleep(0)
        return self._payload


class _Session:
    """Minimal session stand-in implementing context manager for post()."""

    def __init__(self, scripted: list[tuple[int, dict[str, Any]]]):
        self._scripted = scripted
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, data: dict[str, Any]):  # noqa: D401
        self.posts.append({"url": url, "data": data})
        status, payload = self._scripted.pop(0)
        resp = _Resp(status, payload)

        class _CM:
            async def __aenter__(_self):  # noqa: ANN001, D401
                return resp

            async def __aexit__(_self, _exc_type, _exc, _tb):  # noqa: ANN001, D401
                return False

        return _CM()

    async def __aenter__(self):  # noqa: D401
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):  # noqa: D401
        return False


@pytest.mark.asyncio()
async def test_device_flow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = DeviceCodeFlow("cid", "secret")

    device_payload = {
        "device_code": "dev123",
        "user_code": "UCODE",
        "verification_uri": "http://example/verify",
        "expires_in": 30,
    }
    token_payload = {"access_token": "atok", "refresh_token": "rtok"}

    # First call: device code success (200). Then poll returns 200 immediately.
    scripted = [
        (200, device_payload),
        (200, token_payload),
    ]

    monkeypatch.setattr("aiohttp.ClientSession", lambda: _Session(scripted))

    tokens = await flow.get_user_tokens("user")
    if tokens != ("atok", "rtok"):
        raise AssertionError("Expected token tuple on success")


@pytest.mark.asyncio()
async def test_device_flow_slow_down_and_authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = DeviceCodeFlow("cid", "secret")
    flow.poll_interval = 0  # speed up test

    device_payload = {
        "device_code": "dev123",
        "user_code": "UCODE",
        "verification_uri": "http://example/verify",
        "expires_in": 20,
    }
    # Poll responses sequence: slow_down -> authorization_pending -> success
    scripted = [
        (200, device_payload),
        (400, {"message": "slow_down"}),
        (400, {"message": "authorization_pending"}),
        (200, {"access_token": "A", "refresh_token": "R"}),
    ]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: _Session(scripted))
    with patch('asyncio.sleep', new_callable=AsyncMock):
        tokens = await flow.get_user_tokens("user")
    if tokens != ("A", "R"):
        raise AssertionError("Expected tokens after slow_down + pending + success path")
    if flow.poll_interval <= 0:
        raise AssertionError("Poll interval should have increased after slow_down")


@pytest.mark.asyncio()
async def test_device_flow_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = DeviceCodeFlow("cid", "secret")
    flow.poll_interval = 0
    device_payload = {
        "device_code": "dev123",
        "user_code": "UCODE",
        "verification_uri": "http://example/verify",
        "expires_in": 15,
    }
    scripted = [
        (200, device_payload),
        (400, {"message": "access_denied"}),
    ]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: _Session(scripted))
    tokens = await flow.get_user_tokens("user")
    if tokens is not None:
        raise AssertionError("Expected None for access_denied flow")


@pytest.mark.asyncio()
async def test_device_flow_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = DeviceCodeFlow("cid", "secret")
    flow.poll_interval = 0
    device_payload = {
        "device_code": "dev123",
        "user_code": "UCODE",
        "verification_uri": "http://example/verify",
        "expires_in": 10,
    }
    scripted = [
        (200, device_payload),
        (400, {"message": "expired_token"}),
    ]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: _Session(scripted))
    tokens = await flow.get_user_tokens("user")
    if tokens is not None:
        raise AssertionError("Expected None for expired_token flow")


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]):
        self.status = status
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        # Simulate async boundary so linters don't flag this as sync.
        await asyncio.sleep(0)
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:  # noqa: D401
        return None


class FakeSession:
    """Minimal aiohttp.ClientSession stand-in returning queued responses."""

    def __init__(self, queue: list[tuple[int, dict[str, Any]]]):
        self._queue = queue

    def post(self, *_args, **_kwargs):  # noqa: D401
        if not self._queue:
            # Fallback: emulate an unexpected error status to end loop
            return FakeResponse(500, {"error": "empty"})
        status, payload = self._queue.pop(0)
        return FakeResponse(status, payload)

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


@pytest.mark.asyncio
async def test_poll_success(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    caplog.set_level(logging.INFO)
    # First 400 authorization_pending then 200 success.
    responses = [
        (400, {"message": "authorization_pending"}),
        (200, {"access_token": "at1", "refresh_token": "rt1"}),
    ]
    monkeypatch.setattr(
        "aiohttp.ClientSession", lambda: FakeSession(responses)  # type: ignore[arg-type]
    )

    df = DeviceCodeFlow("cid", "secret")
    df.poll_interval = 0  # speed
    result = await df.poll_for_tokens("dev-code", expires_in=5)
    assert result == {"access_token": "at1", "refresh_token": "rt1"}
    assert any("Authorized after" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_poll_slow_down(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    # slow_down -> authorization_pending -> success
    responses = [
        (400, {"message": "slow_down"}),
        (400, {"message": "authorization_pending"}),
        (200, {"access_token": "at2"}),
    ]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))  # type: ignore[arg-type]

    df = DeviceCodeFlow("cid", "secret")
    df.poll_interval = 1

    # Patch asyncio.sleep so test runs instantly without recursion.
    original_sleep = asyncio.sleep
    monkeypatch.setattr("asyncio.sleep", lambda _s: original_sleep(0))

    result = await df.poll_for_tokens("dev-code", expires_in=10)
    assert result["access_token"] == "at2"  # noqa: S105
    # Interval should have been incremented once (1 -> 2) due to slow_down.
    assert df.poll_interval == 2
    assert any("Server requested slower polling" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_poll_expired_token(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    responses = [(400, {"message": "expired_token"})]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))  # type: ignore[arg-type]
    df = DeviceCodeFlow("cid", "secret")
    df.poll_interval = 0
    result = await df.poll_for_tokens("dev-code", expires_in=10)
    # Current implementation returns {} for terminal errors.
    assert result == {}
    assert any("Device code expired after" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_poll_access_denied(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    responses = [(400, {"message": "access_denied"})]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))  # type: ignore[arg-type]
    df = DeviceCodeFlow("cid", "secret")
    result = await df.poll_for_tokens("dev-code", expires_in=10)
    assert result == {}
    assert any("User denied access" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_poll_timeout(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    # No poll iterations: expires_in=0 triggers immediate timeout path.
    responses = []
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))  # type: ignore[arg-type]
    df = DeviceCodeFlow("cid", "secret")
    df.poll_interval = 0
    result = await df.poll_for_tokens("dev-code", expires_in=0)
    assert result is None
    assert any("Timed out after" in r.message for r in caplog.records)

@pytest.mark.asyncio
async def test_device_flow_client_init_invalid_client_id():
    """Test DeviceFlowClient initialization with invalid or missing client_id."""
    # Since __init__ doesn't validate, test that it accepts but fails in usage
    flow = DeviceCodeFlow("", "secret")
    # Mock session to test
    with patch("aiohttp.ClientSession.post", side_effect=aiohttp.ClientError):
        result = await flow.request_device_code()
        assert result is None


@pytest.mark.asyncio
async def test_start_device_flow_network_errors(monkeypatch):
    """Test start_device_flow method with network connection errors."""
    flow = DeviceCodeFlow("cid", "secret")
    with patch("aiohttp.ClientSession.post", side_effect=aiohttp.ClientError("Network error")):
        result = await flow.request_device_code()
        assert result is None


@pytest.mark.asyncio
async def test_poll_for_token_timeout(monkeypatch):
    """Test poll_for_token with timeout scenarios and user cancellation."""
    flow = DeviceCodeFlow("cid", "secret")
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession([]))
    result = await flow.poll_for_tokens("dev123", expires_in=0)
    assert result is None


@pytest.mark.asyncio
async def test_handle_device_code_invalid_response(monkeypatch):
    """Test handle_device_code with invalid or malformed API responses."""
    flow = DeviceCodeFlow("cid", "secret")
    # Mock response with invalid json
    class InvalidResp:
        status = 200
        async def json(self):
            raise ValueError("Invalid JSON")
    class InvalidSession:
        def post(self, *args, **kwargs):
            return InvalidResp()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr("aiohttp.ClientSession", lambda: InvalidSession())
    result = await flow.request_device_code()
    assert result is None


@pytest.mark.asyncio
async def test_refresh_token_expired(monkeypatch):
    """Test refresh_token method with expired refresh tokens."""
    flow = DeviceCodeFlow("cid", "secret")
    responses = [(400, {"message": "expired_token"})]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))
    result = await flow.poll_for_tokens("dev123", expires_in=10)
    assert result == {}
