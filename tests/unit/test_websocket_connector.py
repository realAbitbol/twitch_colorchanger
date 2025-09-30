"""
Unit tests for WebSocketConnector.
"""

import websockets
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.chat.websocket_connector import TwitchEventSubProtocol, WebSocketConnector
from src.errors.eventsub import EventSubConnectionError


class TestWebSocketConnector:
    """Test class for WebSocketConnector functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.connector = WebSocketConnector(
            token="test_token",
            client_id="test_client_id"
        )

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_sets_attributes(self):
        """Test WebSocketConnector initialization sets all attributes."""
        assert self.connector.token == "test_token"
        assert self.connector.client_id == "test_client_id"
        assert self.connector.ws is None

    def test_init_with_custom_url(self):
        """Test WebSocketConnector initialization with custom URL."""
        custom_url = "wss://custom.url.com"
        connector = WebSocketConnector(
            token="test_token",
            client_id="test_client_id",
            ws_url=custom_url
        )
        assert connector.ws_url == custom_url

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test connect establishes WebSocket connection successfully."""
        mock_ws = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect, \
             patch('src.chat.websocket_connector.logging') as mock_logging:
            mock_connect.return_value = mock_ws
            await self.connector.connect()

        assert self.connector.ws == mock_ws
        mock_connect.assert_called_once_with(
            self.connector.ws_url,
            extra_headers={"Client-Id": self.connector.client_id, "Authorization": f"Bearer {self.connector.token}"},
            subprotocols=("twitch-eventsub-ws",),
            ping_interval=30,
            create_protocol=TwitchEventSubProtocol,
        )
        assert mock_logging.info.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_calls_cleanup_first(self):
        """Test connect calls cleanup before establishing new connection."""
        mock_ws = AsyncMock()

        # Set existing connection
        self.connector.ws = Mock()
        self.connector.ws.closed = False

        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect, \
             patch.object(self.connector, '_cleanup_connection', new_callable=AsyncMock) as mock_cleanup:
            mock_connect.return_value = mock_ws
            await self.connector.connect()

        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_raises_event_sub_error_on_failure(self):
        """Test connect raises EventSubConnectionError on connection failure."""
        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

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
        # The logging includes code and reason, so we check that it starts with the expected message
        mock_logging.info.assert_called_once()
        log_call = mock_logging.info.call_args[0][0]
        assert log_call.startswith("🔌 WebSocket disconnected")
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

    def test_get_headers_returns_correct_headers(self):
        """Test _get_headers returns correct headers."""
        headers = self.connector._get_headers()
        assert headers == {
            "Client-Id": self.connector.client_id,
            "Authorization": f"Bearer {self.connector.token}"
        }

    @pytest.mark.asyncio
    async def test_cleanup_connection_already_closed_with_bytes_reason(self):
        """Test _cleanup_connection logs already closed with bytes reason decoded."""
        mock_ws = Mock()
        mock_ws.closed = True
        mock_ws.close_code = 1001
        mock_ws.close_reason = b'bytes_reason'
        self.connector.ws = mock_ws

        with patch('src.chat.websocket_connector.logging') as mock_logging:
            await self.connector._cleanup_connection()

        mock_logging.info.assert_called_once_with("🔌 WebSocket already closed: code=1001, reason=bytes_reason")
        assert self.connector.ws is None

    @pytest.mark.asyncio
    async def test_cleanup_connection_close_error_with_closed_ws(self):
        """Test _cleanup_connection handles close error and logs if ws becomes closed."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        def close_side_effect(*args, **kwargs):
            mock_ws.closed = True
            raise Exception("Close failed")

        mock_ws.close.side_effect = close_side_effect
        mock_ws.close_code = 1002
        mock_ws.close_reason = b'error_reason'
        self.connector.ws = mock_ws

        with patch('src.chat.websocket_connector.logging') as mock_logging:
            await self.connector._cleanup_connection()

        assert mock_logging.warning.call_count == 2
        mock_logging.warning.assert_any_call("⚠️ WebSocket close error: Close failed")
        mock_logging.warning.assert_any_call("⚠️ WebSocket closed with error: code=1002, reason=error_reason")
        assert self.connector.ws is None


class TestTwitchEventSubProtocol:
    """Test class for TwitchEventSubProtocol functionality."""

    @pytest.mark.asyncio
    async def test_pong_logs_with_data(self):
        """Test pong logs message with hex data."""
        protocol = TwitchEventSubProtocol()

        with patch('src.chat.websocket_connector.logging') as mock_logging, \
             patch('websockets.WebSocketClientProtocol.pong', new_callable=AsyncMock):
            await protocol.pong(b'test_data')

        mock_logging.info.assert_called_once_with("🏓 Pong sent to Twitch: 746573745f64617461")

    @pytest.mark.asyncio
    async def test_pong_logs_no_data(self):
        """Test pong logs message with no data."""
        protocol = TwitchEventSubProtocol()

        with patch('src.chat.websocket_connector.logging') as mock_logging, \
             patch('websockets.WebSocketClientProtocol.pong', new_callable=AsyncMock):
            await protocol.pong()

        mock_logging.info.assert_called_once_with("🏓 Pong sent to Twitch: no data")
