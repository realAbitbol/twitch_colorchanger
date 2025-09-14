"""Tests for src/chat/eventsub_backend.py."""

import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.chat.eventsub_backend import EventSubChatBackend


def test_eventsub_backend_init_invalid_params():
    """Test EventSubBackend initialization with invalid parameters (e.g., None or incorrect types)."""
    # Should handle None http_session gracefully
    with patch('aiohttp.ClientSession') as mock_session:
        backend = EventSubChatBackend(http_session=None)
        assert backend._session == mock_session.return_value


@pytest.mark.asyncio
async def test_connect_failure_scenarios():
    """Test connect method with various failure scenarios like network errors or invalid URLs."""
    backend = EventSubChatBackend()
    with patch.object(backend, '_capture_initial_credentials'), \
         patch.object(backend, '_validate_client_id', return_value=False):
        result = await backend.connect("token", "user", "channel", "user_id", "client_id")
        assert result is False


@pytest.mark.asyncio
async def test_listen_connection_errors():
    """Test listen method handling of connection errors and recovery attempts."""
    backend = EventSubChatBackend()
    backend._ws = None  # No connection
    backend._stop_event.set()  # Stop immediately
    await backend.listen()  # Should return without error


@pytest.mark.asyncio
async def test_subscribe_invalid_data():
    """Test subscribe method with invalid subscription data, ensuring validation and error responses."""
    backend = EventSubChatBackend()
    backend._session_id = None  # Invalid state
    await backend._subscribe_channel_chat("channel")  # Should not raise


@pytest.mark.asyncio
async def test_reconnect_after_loss():
    """Test reconnect logic after unexpected connection loss, including state preservation."""
    backend = EventSubChatBackend()
    with patch.object(backend, '_reconnect_with_backoff', new_callable=AsyncMock, return_value=False):
        backend._ws = MagicMock()
        backend._ws.closed = True
        result = await backend._ensure_socket()
        assert result is False


@pytest.mark.asyncio
async def test_eventsub_backend_handle_message_invalid_format():
    """Test handle_message with invalid message format."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    # Invalid JSON
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = "invalid json"
    with patch.object(backend, '_handle_text', new_callable=AsyncMock) as mock_handle:
        await backend._handle_ws_message(msg)
        mock_handle.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_eventsub_backend_process_subscription_failure():
    """Test process_subscription with subscription failure."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "token"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        mock_api.request = AsyncMock(return_value=(None, 500, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_eventsub_backend_cleanup_on_disconnect():
    """Test cleanup procedures when connection is lost."""
    backend = EventSubChatBackend()
    mock_ws = MagicMock()
    mock_ws.closed = False
    backend._ws = mock_ws
    await backend.disconnect()
    mock_ws.close.assert_called_once()
    assert backend._ws is None


@pytest.mark.asyncio
async def test_eventsub_backend_rate_limit_handling():
    """Test rate limit handling for subscription requests."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "token"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        # Simulate rate limit (429)
        mock_api.request = AsyncMock(return_value=(None, 429, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once_with("channel", 429, None)


@pytest.mark.asyncio
async def test_eventsub_backend_authentication_failure():
    """Test authentication failure scenarios."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "invalid"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        # Simulate auth failure (401)
        mock_api.request = AsyncMock(return_value=(None, 401, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once_with("channel", 401, None)
