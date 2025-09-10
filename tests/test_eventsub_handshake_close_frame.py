import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from src.chat.eventsub_backend import EventSubChatBackend


@pytest.mark.asyncio
async def test_handshake_records_close_frame(monkeypatch):
    """Simulate the WebSocket sending a CLOSE welcome frame and ensure the
    detailed handshake records close_code and close_reason."""
    close_code = 4007
    close_reason = "reconnect rejected"

    # Build a minimal welcome-like object the code expects
    class Welcome:
        pass

    welcome = Welcome()
    welcome.type = aiohttp.WSMsgType.CLOSE
    welcome.data = close_code
    # `extra` may contain reason text depending on transport
    welcome.extra = close_reason

    ws_mock = MagicMock()
    ws_mock._request_headers = {"Host": "cell-c.eventsub.wss.twitch.tv"}
    ws_mock.receive = AsyncMock(return_value=welcome)

    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=ws_mock)

    backend = EventSubChatBackend(http_session=session)
    backend._ws_url = "wss://cell-c.eventsub.wss.twitch.tv/ws?challenge=abc"

    ok, details = await backend._open_and_handshake_detailed()

    assert ok is False
    assert isinstance(details, dict)
    # The detailed handshake should surface close code and reason
    assert details.get("close_code") == close_code
    assert details.get("close_reason") == close_reason
    # welcome_type should be recorded for diagnostic purposes
    assert "welcome_type" in details


@pytest.mark.asyncio
async def test_successful_welcome_consumes_pending_session(monkeypatch):
    """If a pending_reconnect_session_id exists it should be cleared on successful handshake."""
    session_id = "AgoQOa8qqQgHQsy6kEA"

    class Welcome:
        pass

    welcome = Welcome()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = '{"payload": {"session": {"id": "%s"}}}' % session_id

    ws_mock = MagicMock()
    ws_mock._request_headers = {}
    ws_mock.receive = AsyncMock(return_value=welcome)

    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=ws_mock)

    backend = EventSubChatBackend(http_session=session)
    backend._pending_reconnect_session_id = session_id
    ok, _ = await backend._open_and_handshake_detailed()

    assert ok is True
    assert backend._pending_reconnect_session_id is None


@pytest.mark.asyncio
async def test_close_triggers_token_refresh_callback(monkeypatch):
    close_code = 4002

    class Welcome:
        pass

    welcome = Welcome()
    welcome.type = aiohttp.WSMsgType.CLOSE
    welcome.data = close_code
    welcome.extra = None

    ws_mock = MagicMock()
    ws_mock._request_headers = {}
    ws_mock.receive = AsyncMock(return_value=welcome)

    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=ws_mock)

    triggered = False

    async def token_refresh():
        nonlocal triggered
        triggered = True
        await asyncio.sleep(0)

    backend = EventSubChatBackend(http_session=session)
    backend._token_invalid_callback = token_refresh

    ok, details = await backend._open_and_handshake_detailed()

    assert ok is False
    # mapped_action should indicate token_refresh and token refresh task scheduled
    assert details.get("mapped_action") == "token_refresh"
    # allow scheduled task to run in event loop
    await asyncio.sleep(0)
    assert triggered is True


@pytest.mark.asyncio
async def test_full_reconnect_flow_rebuilds_subscriptions(monkeypatch):
    """Simulate a session_reconnect then a successful TEXT welcome and ensure
    subscriptions are rebuilt via _subscribe_channel_chat calls."""
    # Prepare backend with some channels
    backend = EventSubChatBackend()
    backend._channels = ["chan1", "chan2"]
    backend._channel_ids = {"chan1": "1", "chan2": "2"}
    backend._token = "t"
    backend._client_id = "c"

    # Simulate receiving a session_reconnect message
    session_msg = type("Msg", (), {})()
    session_msg.type = aiohttp.WSMsgType.TEXT
    session_msg.data = '{"type": "session_reconnect", "payload": {"session": {"reconnect_url": "wss://r"}}}'

    # Then simulate the ws returning a successful TEXT welcome with session id
    welcome = type("Welcome", (), {})()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = '{"payload": {"session": {"id": "s123"}}}'

    # Mock ws and session
    ws_mock = MagicMock()
    ws_mock.closed = False
    # _receive_one will yield session_msg then None to end
    backend._receive_one = AsyncMock(side_effect=[session_msg, None])
    backend._ws = ws_mock

    # Replace _safe_close, _reconnect_with_backoff and handshake to simulate behavior
    backend._safe_close = AsyncMock()
    # When reconnect runs it should use our _open_and_handshake_detailed; patch it
    async def fake_open_and_handshake():
        # set session id as would be on successful handshake
        backend._session_id = "s123"
        await asyncio.sleep(0)
        return True, {"session_id": "s123"}

    backend._open_and_handshake_detailed = AsyncMock(side_effect=fake_open_and_handshake)

    # Spy on _subscribe_channel_chat
    backend._subscribe_channel_chat = AsyncMock()

    # Trigger the reconnect flow directly
    backend._reconnect_requested = True
    ok = await backend._reconnect_with_backoff()

    assert ok is True
    # _subscribe_channel_chat should be called for each channel at least once
    assert backend._subscribe_channel_chat.call_count >= len(backend._channels)


@pytest.mark.asyncio
async def test_session_stale_triggers_full_resubscribe(monkeypatch):
    """Session stale close code should set force_full_resubscribe and cause
    an extra explicit resubscribe on reconnect."""
    backend = EventSubChatBackend()
    backend._channels = ["a"]
    backend._channel_ids = {"a": "1"}
    backend._token = "t"
    backend._client_id = "c"

    # Simulate close frame with code 4007
    welcome = type("Welcome", (), {})()
    welcome.type = aiohttp.WSMsgType.CLOSE
    welcome.data = 4007
    welcome.extra = None

    ws_mock = MagicMock()
    ws_mock._request_headers = {}
    ws_mock.receive = AsyncMock(return_value=welcome)

    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=ws_mock)
    backend._session = session

    # token invalid callback not relevant here; run handshake
    ok, details = await backend._open_and_handshake_detailed()
    assert ok is False
    assert details.get("mapped_action") == "session_stale"

    # Now simulate successful reconnect and observe force_full_resubscribe behavior
    backend._open_and_handshake_detailed = AsyncMock(return_value=(True, {"session_id": "s"}))
    backend._subscribe_channel_chat = AsyncMock()
    backend._reconnect_requested = True
    res = await backend._reconnect_with_backoff()
    assert res is True
    # Because force_full_resubscribe was set, the subscribe function should have been called twice for the channel
    assert backend._subscribe_channel_chat.call_count >= 2
