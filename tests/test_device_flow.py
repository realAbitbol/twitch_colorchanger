from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.token.device_flow import DeviceCodeFlow


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
            async def __aenter__(self_inner):  # noqa: ANN001, D401
                return resp

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001, D401
                return False

        return _CM()

    async def __aenter__(self):  # noqa: D401
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
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

import pytest


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

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
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

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_poll_success(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
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
    # Event name is truncated with an ellipsis due to width; check fragment.
    assert any(
        ("authorization_success" in r.message)
        or ("authorization_succe" in r.message)  # truncated variant
        for r in caplog.records
    )


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
    assert result["access_token"] == "at2"
    # Interval should have been incremented once (1 -> 2) due to slow_down.
    assert df.poll_interval == 2
    assert any("device_flow_slow_down" in r.message for r in caplog.records)


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
    assert any("device_flow_expired_token" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_poll_access_denied(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG", "1")
    responses = [(400, {"message": "access_denied"})]
    monkeypatch.setattr("aiohttp.ClientSession", lambda: FakeSession(responses))  # type: ignore[arg-type]
    df = DeviceCodeFlow("cid", "secret")
    result = await df.poll_for_tokens("dev-code", expires_in=10)
    assert result == {}
    assert any("device_flow_access_denied" in r.message for r in caplog.records)


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
    assert any("device_flow_timeout" in r.message for r in caplog.records)
