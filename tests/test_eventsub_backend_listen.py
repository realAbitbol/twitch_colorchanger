import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from src.chat.eventsub_backend import EventSubChatBackend


@pytest.mark.asyncio
async def test_receive_one_timeout_no_stale():
    """Test _receive_one returns None on timeout when not stale."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._last_activity = asyncio.get_event_loop().time()
    backend._stale_threshold = 100.0  # high threshold

    # Mock receive to raise TimeoutError
    backend._ws.receive = AsyncMock(side_effect=asyncio.TimeoutError)

    result = await backend._receive_one()
    assert result is None
    backend._ws.receive.assert_called_once()


@pytest.mark.asyncio
async def test_receive_one_timeout_stale_reconnect():
    """Test _receive_one triggers reconnect on timeout when stale."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._last_activity = 0  # old activity
    backend._stale_threshold = 10.0

    backend._ws.receive = AsyncMock(side_effect=asyncio.TimeoutError)
    backend._reconnect_with_backoff = AsyncMock(return_value=True)

    result = await backend._receive_one()
    assert result is None
    backend._reconnect_with_backoff.assert_called_once()


@pytest.mark.asyncio
async def test_receive_one_cancelled_error():
    """Test _receive_one handles CancelledError."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.receive = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await backend._receive_one()


@pytest.mark.asyncio
async def test_receive_one_other_exception():
    """Test _receive_one triggers reconnect on other exceptions."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.receive = AsyncMock(side_effect=Exception("network error"))
    backend._reconnect_with_backoff = AsyncMock(return_value=True)

    result = await backend._receive_one()
    assert result is None
    backend._reconnect_with_backoff.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ws_message_text():
    """Test _handle_ws_message processes TEXT messages."""
    backend = EventSubChatBackend()
    backend._handle_text = AsyncMock()

    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = '{"type": "notification"}'

    result = await backend._handle_ws_message(msg)
    assert result is False
    backend._handle_text.assert_called_once_with(msg.data)


@pytest.mark.asyncio
async def test_handle_ws_message_closed():
    """Test _handle_ws_message triggers reconnect on CLOSED."""
    backend = EventSubChatBackend()
    backend._reconnect_with_backoff = AsyncMock(return_value=True)

    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.CLOSED
    msg.data = 1000

    result = await backend._handle_ws_message(msg)
    assert result is False
    backend._reconnect_with_backoff.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ws_message_error():
    """Test _handle_ws_message triggers reconnect on ERROR."""
    backend = EventSubChatBackend()
    backend._reconnect_with_backoff = AsyncMock(return_value=True)

    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.ERROR
    msg.data = "connection error"

    result = await backend._handle_ws_message(msg)
    assert result is False
    backend._reconnect_with_backoff.assert_called_once()


@pytest.mark.asyncio
async def test_listen_normal_message():
    """Test listen processes a normal TEXT message."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.closed = False
    backend._stop_event = asyncio.Event()

    backend._maybe_verify_subs = AsyncMock(side_effect=lambda now: backend._stop_event.set())
    backend._maybe_reconnect = AsyncMock(return_value=False)
    backend._ensure_socket = AsyncMock(return_value=True)
    backend._receive_one = AsyncMock(return_value=MagicMock(type=aiohttp.WSMsgType.TEXT, data='{"type": "notification"}'))
    backend._handle_ws_message = AsyncMock(return_value=False)

    await backend.listen()

    backend._receive_one.assert_called_once()
    backend._handle_ws_message.assert_called_once()


@pytest.mark.asyncio
async def test_listen_reconnect_triggered():
    """Test listen handles reconnect trigger."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.closed = False
    backend._stop_event = asyncio.Event()

    backend._maybe_verify_subs = AsyncMock(side_effect=lambda now: backend._stop_event.set())
    backend._maybe_reconnect = AsyncMock(return_value=True)  # reconnect triggered

    await backend.listen()

    backend._maybe_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_socket_closed():
    """Test _ensure_socket reconnects when WebSocket is closed."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.closed = True
    backend._reconnect_with_backoff = AsyncMock(return_value=True)

    result = await backend._ensure_socket()
    assert result is True
    backend._reconnect_with_backoff.assert_called_once()
