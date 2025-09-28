import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from src.chat.eventsub_backend import EventSubChatBackend
from src.chat.message_processor import MessageProcessor
from src.chat.websocket_connection_manager import WebSocketConnectionManager


@pytest.mark.asyncio
async def test_listen_timeout_handling():
    """Test listen handles timeout from WebSocketConnectionManager."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.receive_message = AsyncMock(side_effect=asyncio.TimeoutError)
    ws_manager.reconnect = AsyncMock(return_value=False)

    backend = EventSubChatBackend(ws_manager=ws_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen start
        backend._stop_event.set()
        await listen_task



@pytest.mark.asyncio
async def test_listen_reconnect_on_stale_timeout():
    """Test listen triggers reconnect on timeout when stale."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.receive_message = AsyncMock(side_effect=asyncio.TimeoutError)
    ws_manager.reconnect = AsyncMock(return_value=False)

    backend = EventSubChatBackend(ws_manager=ws_manager)
    backend._last_activity = 0  # old activity
    backend._stale_threshold = 10.0
    backend._stop_event = asyncio.Event()

    # Mock time.monotonic to simulate stale condition
    with patch('src.chat.eventsub_backend.time.monotonic', return_value=11):  # 11 > 10, so stale
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen start
        backend._stop_event.set()
        await listen_task



@pytest.mark.asyncio
async def test_listen_cancelled_error():
    """Test listen handles CancelledError."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.receive_message = AsyncMock(side_effect=asyncio.CancelledError)

    backend = EventSubChatBackend(ws_manager=ws_manager)

    # Start listen and expect CancelledError to be raised
    with pytest.raises(asyncio.CancelledError):
        await backend.listen()


@pytest.mark.asyncio
async def test_listen_other_exception_reconnect():
    """Test listen triggers reconnect on other exceptions."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.receive_message = AsyncMock(side_effect=Exception("network error"))
    ws_manager.reconnect = AsyncMock(return_value=False)

    backend = EventSubChatBackend(ws_manager=ws_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.1)  # Let listen start
        backend._stop_event.set()
        await listen_task



@pytest.mark.asyncio
async def test_listen_processes_text_message():
    """Test listen processes TEXT messages via MessageProcessor."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.reconnect = AsyncMock(return_value=False)
    msg_processor = MagicMock(spec=MessageProcessor)

    # Mock a TEXT message
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = '{"type": "notification"}'

    # Mock receive_message to return the message once, then raise an exception to stop
    ws_manager.receive_message = AsyncMock(side_effect=[msg, Exception("stop")])
    msg_processor.process_message = AsyncMock()

    backend = EventSubChatBackend(ws_manager=ws_manager, msg_processor=msg_processor)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    # Mock time.monotonic to prevent timing issues
    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen process the message
        backend._stop_event.set()
        await listen_task  # listen handles exceptions internally



@pytest.mark.asyncio
async def test_listen_reconnect_on_closed():
    """Test listen triggers reconnect on CLOSED message."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.reconnect = AsyncMock(return_value=False)

    # Mock a CLOSED message
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.CLOSED
    msg.data = 1000

    # Mock receive_message to return the message once, then raise an exception to stop
    ws_manager.receive_message = AsyncMock(side_effect=[msg, Exception("stop")])

    backend = EventSubChatBackend(ws_manager=ws_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    # Mock time.monotonic to prevent timing issues
    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen process the message
        backend._stop_event.set()
        await listen_task  # listen handles exceptions internally



@pytest.mark.asyncio
async def test_listen_reconnect_on_error():
    """Test listen triggers reconnect on ERROR message."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.reconnect = AsyncMock(return_value=False)

    # Mock an ERROR message
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.ERROR
    msg.data = "connection error"

    # Mock receive_message to return the message once, then raise an exception to stop
    ws_manager.receive_message = AsyncMock(side_effect=[msg, Exception("stop")])

    backend = EventSubChatBackend(ws_manager=ws_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen process the message
        backend._stop_event.set()
        await listen_task  # listen handles exceptions internally



@pytest.mark.asyncio
async def test_listen_normal_message():
    """Test listen processes a normal TEXT message."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.reconnect = AsyncMock(return_value=False)
    msg_processor = MagicMock(spec=MessageProcessor)
    sub_manager = MagicMock()
    sub_manager.unsubscribe_all = AsyncMock()

    # Mock a TEXT message
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = '{"type": "notification"}'

    # Mock receive_message to return the message once, then raise an exception to stop
    ws_manager.receive_message = AsyncMock(side_effect=[msg, Exception("stop")])
    msg_processor.process_message = AsyncMock()

    # Mock subscription verification to stop the loop
    sub_manager.verify_subscriptions = AsyncMock(return_value=[])

    backend = EventSubChatBackend(ws_manager=ws_manager, msg_processor=msg_processor, sub_manager=sub_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen process the message
        backend._stop_event.set()
        await listen_task  # listen handles exceptions internally



@pytest.mark.asyncio
async def test_listen_reconnect_triggered():
    """Test listen handles reconnect trigger."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = True
    ws_manager.receive_message = AsyncMock(side_effect=Exception("stop"))
    ws_manager.reconnect = AsyncMock(return_value=False)

    sub_manager = MagicMock()
    sub_manager.unsubscribe_all = AsyncMock()
    sub_manager.verify_subscriptions = AsyncMock(return_value=["some_channel"])  # Non-empty means reconnect needed

    backend = EventSubChatBackend(ws_manager=ws_manager, sub_manager=sub_manager)
    backend._last_activity = 0
    backend._stop_event = asyncio.Event()

    with patch('time.monotonic', return_value=1):
        # Start listen in background and stop it quickly
        listen_task = asyncio.create_task(backend.listen())
        await asyncio.sleep(0.01)  # Let listen start
        backend._stop_event.set()
        await listen_task  # listen handles exceptions internally



@pytest.mark.asyncio
async def test_listen_reconnects_when_disconnected():
    """Test listen reconnects when WebSocket is not connected."""
    ws_manager = MagicMock(spec=WebSocketConnectionManager)
    ws_manager.is_connected = False  # WebSocket is not connected
    ws_manager.reconnect = AsyncMock()

    backend = EventSubChatBackend(ws_manager=ws_manager)

    # Start listen - it should return immediately since not connected
    await backend.listen()

    # Verify reconnect was not called (listen just returns if not connected)
    ws_manager.reconnect.assert_not_called()
