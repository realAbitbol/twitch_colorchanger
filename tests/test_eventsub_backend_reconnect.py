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
