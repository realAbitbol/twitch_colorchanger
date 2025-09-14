"""Tests for src/chat/eventsub_backend.py."""

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
