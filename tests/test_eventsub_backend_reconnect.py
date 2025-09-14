import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.chat.eventsub_backend import EventSubChatBackend


@pytest.mark.asyncio
async def test_eventsub_session_reconnect_triggers_reconnect(monkeypatch):
    """
    Simulate a session_reconnect instruction and verify that:
    - The backend updates its ws_url
    - The backend triggers a reconnect using the new URL
    - The handshake uses the new URL
    """
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.closed = False
    backend._stop_event.clear()
    # _ensure_socket returns True first, then False to exit loop after reconnect
    backend._ensure_socket = AsyncMock(side_effect=[True, False])
    backend._maybe_verify_subs = AsyncMock()

    backend._reconnect_with_backoff = AsyncMock(return_value=True)
    backend._last_activity = 0
    backend._ws_url = "wss://eventsub.wss.twitch.tv/ws"

    # Prepare a session_reconnect message as would be received from Twitch
    new_url = "wss://eventsub.wss.twitch.tv/ws_reconnect_123"
    # The backend expects a JSON string with a top-level 'type' field
    session_reconnect_msg = type("Msg", (), {})()
    session_reconnect_msg.type = 1  # aiohttp.WSMsgType.TEXT
    session_reconnect_msg.data = (
        f'{{"type": "session_reconnect", "payload": {{"session": {{"reconnect_url": "{new_url}"}}}}}}'
    )
    # After the reconnect, return None to exit the loop
    backend._receive_one = AsyncMock(side_effect=[session_reconnect_msg, None])

    # Simulate listen running in the background
    listen_task = asyncio.create_task(backend.listen())
    await asyncio.sleep(0.05)  # Let the listen loop process the message
    backend._stop_event.set()
    await asyncio.sleep(0.01)
    listen_task.cancel()
    await listen_task
    # The backend should have set the new URL and triggered reconnect
    assert backend._ws_url == new_url
    backend._reconnect_with_backoff.assert_called()
    # After reconnect, the flag should be reset
    assert backend._reconnect_requested is False


@pytest.mark.asyncio
async def test_extract_reconnect_info_invalid_data():
    """Test _extract_reconnect_info handles invalid data."""
    backend = EventSubChatBackend()

    result = backend._extract_reconnect_info("not a dict")
    assert result == (None, None, None, {})


@pytest.mark.asyncio
async def test_extract_reconnect_info_no_payload():
    """Test _extract_reconnect_info handles data without payload."""
    backend = EventSubChatBackend()

    data = {"type": "session_reconnect"}
    result = backend._extract_reconnect_info(data)
    assert result == (None, None, None, {})


@pytest.mark.asyncio
async def test_extract_reconnect_info_no_session():
    """Test _extract_reconnect_info handles payload without session."""
    backend = EventSubChatBackend()

    data = {"payload": {}}
    result = backend._extract_reconnect_info(data)
    assert result == (None, None, None, {})


@pytest.mark.asyncio
async def test_extract_reconnect_info_no_url():
    """Test _extract_reconnect_info handles session without reconnect_url."""
    backend = EventSubChatBackend()

    data = {"payload": {"session": {"id": "session123"}}}
    result = backend._extract_reconnect_info(data)
    assert result == (None, None, None, {"id": "session123"})


@pytest.mark.asyncio
async def test_extract_reconnect_info_url_parse_error():
    """Test _extract_reconnect_info handles URL parse error."""
    backend = EventSubChatBackend()

    data = {"payload": {"session": {"reconnect_url": "invalid://url"}}}
    result = backend._extract_reconnect_info(data)
    assert result[0] == "invalid://url"
    assert result[1] is None
    assert result[2] is None


@pytest.mark.asyncio
async def test_update_reconnect_state_success():
    """Test _update_reconnect_state updates state correctly."""
    backend = EventSubChatBackend()
    backend._ws_url = "old_url"
    backend._pending_reconnect_session_id = None
    backend._pending_challenge = None

    backend._update_reconnect_state("new_url", "session123", "challenge123", {"id": "session123"})
    assert backend._ws_url == "new_url"
    assert backend._pending_reconnect_session_id == "session123"
    assert backend._pending_challenge == "challenge123"


@pytest.mark.asyncio
async def test_handle_session_reconnect_invalid_url():
    """Test _handle_session_reconnect handles invalid URL."""
    backend = EventSubChatBackend()
    backend._safe_close = AsyncMock()

    data = {"payload": {"session": {"reconnect_url": "http://invalid"}}}
    await backend._handle_session_reconnect(data)
    backend._safe_close.assert_not_called()
    assert backend._reconnect_requested is False


@pytest.mark.asyncio
async def test_handle_session_reconnect_missing_url():
    """Test _handle_session_reconnect handles missing URL."""
    backend = EventSubChatBackend()
    backend._safe_close = AsyncMock()

    data = {"payload": {"session": {}}}
    await backend._handle_session_reconnect(data)
    backend._safe_close.assert_not_called()
    assert backend._reconnect_requested is False
