"""
Unit tests for WebSocketConnector.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from src.chat.websocket_connector import WebSocketConnector
from src.errors.eventsub import EventSubConnectionError


class TestWebSocketConnector:
    """Test class for WebSocketConnector functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.session = Mock()
        self.connector = WebSocketConnector(
            session=self.session,
            token="test_token",
            client_id="test_client_id"
        )

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_sets_attributes(self):
        """Test WebSocketConnector initialization sets all attributes."""
        assert self.connector.session == self.session
        assert self.connector.token == "test_token"
        assert self.connector.client_id == "test_client_id"
        assert self.connector.ws is None

    def test_init_with_custom_url(self):
        """Test WebSocketConnector initialization with custom URL."""
        custom_url = "wss://custom.url.com"
        connector = WebSocketConnector(
            session=self.session,
            token="test_token",
            client_id="test_client_id",
            ws_url=custom_url
        )
        assert connector.ws_url == custom_url

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test connect establishes WebSocket connection successfully."""
        mock_ws = AsyncMock()
        self.session.ws_connect = AsyncMock(return_value=mock_ws)

        with patch('src.chat.websocket_connector.logging') as mock_logging:
            await self.connector.connect()

        assert self.connector.ws == mock_ws
        self.session.ws_connect.assert_called_once()
        mock_logging.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_calls_cleanup_first(self):
        """Test connect calls cleanup before establishing new connection."""
        mock_ws = AsyncMock()
        self.session.ws_connect = AsyncMock(return_value=mock_ws)

        # Set existing connection
        self.connector.ws = Mock()
        self.connector.ws.closed = False

        with patch.object(self.connector, '_cleanup_connection', new_callable=AsyncMock) as mock_cleanup:
            await self.connector.connect()

        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_raises_event_sub_error_on_failure(self):
        """Test connect raises EventSubConnectionError on connection failure."""
        self.session.ws_connect.side_effect = Exception("Connection failed")

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.connector.connect()

        assert "WebSocket connection failed" in str(exc_info.value)
        assert exc_info.value.operation_type == "connect"

    @pytest.mark.asyncio
    async def test_disconnect_calls_cleanup(self):
        """Test disconnect calls cleanup method."""
        with patch.object(self.connector, '_cleanup_connection', new_callable=AsyncMock) as mock_cleanup:
            await self.connector.disconnect()

        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_connection_calls_cleanup(self):
        """Test cleanup_connection calls cleanup method."""
        with patch.object(self.connector, '_cleanup_connection', new_callable=AsyncMock) as mock_cleanup:
            await self.connector.cleanup_connection()

        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_connection_closes_open_connection(self):
        """Test _cleanup_connection closes open WebSocket connection."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        self.connector.ws = mock_ws

        with patch('src.chat.websocket_connector.logging') as mock_logging:
            await self.connector._cleanup_connection()

        mock_ws.close.assert_called_once_with(code=1000)
        mock_logging.info.assert_called_once_with("🔌 WebSocket disconnected")
        assert self.connector.ws is None

    @pytest.mark.asyncio
    async def test_cleanup_connection_handles_close_error(self):
        """Test _cleanup_connection handles close errors gracefully."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.close.side_effect = Exception("Close failed")
        self.connector.ws = mock_ws

        with patch('src.chat.websocket_connector.logging') as mock_logging:
            await self.connector._cleanup_connection()

        mock_logging.warning.assert_called_once()
        assert self.connector.ws is None

    @pytest.mark.asyncio
    async def test_cleanup_connection_skips_closed_connection(self):
        """Test _cleanup_connection skips already closed connections."""
        mock_ws = Mock()
        mock_ws.closed = True
        self.connector.ws = mock_ws

        await self.connector._cleanup_connection()

        # close should not be called on closed connection
        mock_ws.close.assert_not_called()
        assert self.connector.ws is None

    @pytest.mark.asyncio
    async def test_cleanup_connection_handles_no_connection(self):
        """Test _cleanup_connection handles case with no connection."""
        self.connector.ws = None

        await self.connector._cleanup_connection()

        # Should not raise any errors
        assert self.connector.ws is None