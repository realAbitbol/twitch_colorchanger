"""
Unit tests for ReconnectionManager.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.chat.reconnection_manager import ReconnectionManager
from src.errors.eventsub import EventSubConnectionError


class TestReconnectionManager:
    """Test class for ReconnectionManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.connector = Mock()
        self.stop_event = asyncio.Event()
        self.manager = ReconnectionManager(self.connector, self.stop_event)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_reconnect_calls_reconnect_once(self):
        """Test reconnect delegates to _reconnect_once."""
        with patch.object(self.manager, '_reconnect_once', new_callable=AsyncMock) as mock_reconnect:
            mock_reconnect.return_value = True
            result = await self.manager.reconnect()

        assert result is True
        mock_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_once_success(self):
        """Test _reconnect_once succeeds."""
        self.connector.connect = AsyncMock()
        self.connector.disconnect = AsyncMock()

        result = await self.manager._reconnect_once()

        assert result is True
        self.connector.disconnect.assert_called_once()
        self.connector.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_once_checks_circuit_breaker(self):
        """Test _reconnect_once checks circuit breaker state."""
        # Mock the circuit breaker as closed
        mock_cb = Mock()
        mock_cb.is_open = False
        self.manager.circuit_breaker = mock_cb

        self.connector.connect = AsyncMock()
        self.connector.disconnect = AsyncMock()

        result = await self.manager._reconnect_once()

        assert result is True
        self.connector.disconnect.assert_called_once()
        self.connector.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_once_circuit_breaker_open(self):
        """Test _reconnect_once returns False when circuit breaker is open."""
        # Mock the circuit breaker as open
        mock_cb = Mock()
        mock_cb.is_open = True
        self.manager.circuit_breaker = mock_cb

        result = await self.manager._reconnect_once()

        assert result is False
        self.connector.disconnect.assert_not_called()
        self.connector.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_challenge_success(self):
        """Test handle_challenge succeeds with valid challenge."""
        mock_ws = AsyncMock()
        mock_msg = Mock()
        mock_msg.type = 1  # WSMsgType.TEXT
        mock_msg.data = '{"challenge": "test_challenge"}'
        mock_ws.receive = AsyncMock(return_value=mock_msg)
        self.connector.ws = mock_ws

        with patch('json.loads', return_value={"challenge": "test_challenge"}):
            await self.manager.handle_challenge("test_challenge")

        mock_ws.send.assert_called_once_with('{"type": "challenge_response", "challenge": "test_challenge"}')

    @pytest.mark.asyncio
    async def test_handle_challenge_no_websocket(self):
        """Test handle_challenge does nothing when no WebSocket."""
        self.connector.ws = None

        await self.manager.handle_challenge("test_challenge")

        # Should not raise or do anything

    @pytest.mark.asyncio
    async def test_handle_challenge_no_pending_challenge(self):
        """Test handle_challenge does nothing when no pending challenge."""
        self.connector.ws = Mock()

        await self.manager.handle_challenge(None)

        # Should not raise or do anything

    @pytest.mark.asyncio
    async def test_handle_challenge_raises_on_invalid_message_type(self):
        """Test handle_challenge raises on invalid message type."""
        mock_ws = AsyncMock()
        mock_msg = Mock()
        mock_msg.type = 2  # Not TEXT
        mock_ws.receive = AsyncMock(return_value=mock_msg)
        self.connector.ws = mock_ws

        with pytest.raises(EventSubConnectionError):
            await self.manager.handle_challenge("test_challenge")

    @pytest.mark.asyncio
    async def test_handle_challenge_raises_on_challenge_mismatch(self):
        """Test handle_challenge raises on challenge mismatch."""
        mock_ws = AsyncMock()
        mock_msg = Mock()
        mock_msg.type = 1  # WSMsgType.TEXT
        mock_msg.data = '{"challenge": "wrong_challenge"}'
        mock_ws.receive = AsyncMock(return_value=mock_msg)
        self.connector.ws = mock_ws

        with patch('json.loads', return_value={"challenge": "wrong_challenge"}), \
             pytest.raises(EventSubConnectionError):
            await self.manager.handle_challenge("test_challenge")

    def test_jitter_returns_min_when_equal(self):
        """Test _jitter returns min value when a == b."""
        result = self.manager._jitter(5.0, 5.0)
        assert result == 5.0

    def test_jitter_returns_value_in_range(self):
        """Test _jitter returns value within specified range."""
        result = self.manager._jitter(1.0, 3.0)
        assert 1.0 <= result <= 3.0
