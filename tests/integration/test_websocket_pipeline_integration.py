"""
Integration tests for the full WebSocket connection and message processing pipeline.

These tests simulate the complete WebSocket pipeline using realistic mocks that match
the websockets API exactly. This catches API mismatches during test execution rather
than runtime, preventing the need for manual app restarts.
"""

import asyncio
import json
from typing import Any, AsyncIterator, NamedTuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.chat.message_coordinator import MessageCoordinator
from src.chat.message_transceiver import MessageTransceiver, WSMessage
from src.chat.websocket_connector import WebSocketConnector
from src.errors.eventsub import EventSubConnectionError


class MockWebSocketMessage(NamedTuple):
    """Mock WebSocket message that matches websockets API."""
    type: str
    data: Any


class MockWebSocketClientProtocol:
    """Realistic mock of websockets.WebSocketClientProtocol that matches the API exactly."""

    def __init__(self, messages_to_send: list[dict[str, Any]] | None = None):
        self.messages_to_send = messages_to_send or []
        self.sent_messages: list[str] = []
        self.closed = False
        self.close_code = None
        self.close_reason = None
        # Convert dict messages to MockWebSocketMessage objects
        self._message_iter = iter([
            MockWebSocketMessage(type=msg.get("type", "text"), data=msg.get("data", ""))
            for msg in self.messages_to_send
        ])

    async def send(self, message: str) -> None:
        """Send a message (matches websockets API)."""
        if self.closed:
            raise Exception("WebSocket is closed")
        self.sent_messages.append(message)

    async def recv(self) -> MockWebSocketMessage:
        """Receive a message (matches websockets API)."""
        if self.closed:
            raise Exception("WebSocket is closed")
        try:
            return next(self._message_iter)
        except StopIteration:
            # Simulate connection closed when no more messages
            raise Exception("Connection closed")

    def __aiter__(self):
        """Async iterator (matches websockets API)."""
        return self

    async def __anext__(self) -> MockWebSocketMessage:
        """Async iterator next (matches websockets API)."""
        try:
            return await self.recv()
        except Exception:
            raise StopAsyncIteration

    async def close(self, code: int = 1000) -> None:
        """Close the connection (matches websockets API)."""
        if not self.closed:
            self.closed = True
            self.close_code = code

    async def pong(self, data: bytes = b'') -> None:
        """Send pong response (matches websockets API)."""
        pass  # Mock implementation


@pytest.mark.integration
class TestWebSocketPipelineIntegration:
    """Integration tests for the complete WebSocket pipeline."""

    @pytest.fixture
    async def mock_websocket_with_messages(self):
        """Create a mock WebSocket with predefined messages."""
        messages = [
            {"type": "text", "data": '{"type": "session_welcome", "id": "123"}'},
            {"type": "text", "data": '{"type": "notification", "event": {"color": "red"}}'},
            {"type": "ping", "data": b"ping"},
        ]
        return MockWebSocketClientProtocol(messages)

    @pytest.fixture
    async def websocket_connector(self):
        """Create a WebSocketConnector instance."""
        return WebSocketConnector(
            token="test_token",
            client_id="test_client_id"
        )

    @pytest.fixture
    async def message_transceiver(self, websocket_connector):
        """Create a MessageTransceiver instance."""
        last_activity = [0.0]
        return MessageTransceiver(websocket_connector, last_activity)

    @pytest.fixture
    async def message_coordinator(self):
        """Create a MessageCoordinator with mocked backend."""
        backend = Mock()
        backend._last_activity = 0.0
        backend._msg_processor = Mock()
        backend._msg_processor.process_message = AsyncMock()
        return MessageCoordinator(backend)

    @pytest.mark.asyncio
    async def test_should_establish_websocket_connection_successfully(
        self, websocket_connector, mock_websocket_with_messages
    ):
        """Test successful WebSocket connection establishment."""
        # Arrange
        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_websocket_with_messages

            # Act
            await websocket_connector.connect()

            # Assert
            assert websocket_connector.ws == mock_websocket_with_messages
            mock_connect.assert_called_once()
            call_args = mock_connect.call_args
            assert call_args[1]['extra_headers']['Authorization'] == 'Bearer test_token'
            assert call_args[1]['extra_headers']['Client-Id'] == 'test_client_id'
            assert call_args[1]['subprotocols'] == ('twitch-eventsub-ws',)

    @pytest.mark.asyncio
    async def test_should_validate_websocket_api_attributes_after_connection(
        self, websocket_connector, mock_websocket_with_messages
    ):
        """Test that WebSocket connection validates required API attributes."""
        # Arrange
        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_websocket_with_messages

            # Act & Assert - should not raise any exceptions
            await websocket_connector.connect()

            # Verify the WebSocket has all required attributes
            assert hasattr(websocket_connector.ws, 'closed')
            assert hasattr(websocket_connector.ws, 'close')
            assert hasattr(websocket_connector.ws, 'send')
            assert hasattr(websocket_connector.ws, 'recv')
            assert hasattr(websocket_connector.ws, '__aiter__')

    @pytest.mark.asyncio
    async def test_should_receive_and_process_messages_through_pipeline(
        self, message_transceiver, message_coordinator, mock_websocket_with_messages
    ):
        """Test receiving and processing messages through the full pipeline."""
        # Arrange
        message_transceiver.connector.ws = mock_websocket_with_messages
        message_coordinator.backend._msg_processor.process_message = AsyncMock()

        # Act
        message1 = await message_transceiver.receive_message()
        result1 = await message_coordinator.handle_message(message1)

        message2 = await message_transceiver.receive_message()
        result2 = await message_coordinator.handle_message(message2)

        # Assert
        assert message1.type == "text"
        assert "session_welcome" in message1.data
        assert result1 is True  # Continue processing

        assert message2.type == "text"
        assert "notification" in message2.data
        assert result2 is True  # Continue processing

        # Verify message processor was called for text messages
        assert message_coordinator.backend._msg_processor.process_message.call_count == 2

    @pytest.mark.asyncio
    async def test_should_handle_ping_messages_correctly(
        self, message_transceiver, message_coordinator, mock_websocket_with_messages
    ):
        """Test handling of ping messages in the pipeline."""
        # Arrange
        message_transceiver.connector.ws = mock_websocket_with_messages
        message_coordinator.backend._ws_manager = Mock()
        message_coordinator.backend._ws_manager.connector = Mock()
        message_coordinator.backend._ws_manager.connector.ws = mock_websocket_with_messages

        # Skip first two messages to get to ping
        await message_transceiver.receive_message()
        await message_transceiver.receive_message()
        ping_message = await message_transceiver.receive_message()

        # Act
        result = await message_coordinator.handle_message(ping_message)

        # Assert
        assert ping_message.type == "ping"
        assert result is True  # Continue processing
        # Ping should trigger pong response
        # Note: Our mock doesn't track pong calls, but in real implementation it would

    @pytest.mark.asyncio
    async def test_should_handle_connection_errors_gracefully(
        self, websocket_connector
    ):
        """Test graceful handling of connection errors."""
        # Arrange
        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Network unreachable")

            # Act & Assert
            with pytest.raises(EventSubConnectionError) as exc_info:
                await websocket_connector.connect()

            assert "WebSocket connection failed" in str(exc_info.value)
            assert exc_info.value.operation_type == "connect"

    @pytest.mark.asyncio
    async def test_should_handle_message_receive_timeout(
        self, message_transceiver
    ):
        """Test handling of message receive timeouts."""
        # Arrange
        mock_ws = MockWebSocketClientProtocol([])  # Empty messages list
        mock_ws.closed = False
        message_transceiver.connector.ws = mock_ws

        # Mock asyncio.wait_for to simulate timeout
        with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError()):

            # Act & Assert
            with pytest.raises(EventSubConnectionError) as exc_info:
                await message_transceiver.receive_message()

            assert "WebSocket receive timeout" in str(exc_info.value)
            assert exc_info.value.operation_type == "receive"

    @pytest.mark.asyncio
    async def test_should_handle_websocket_closed_during_receive(
        self, message_transceiver
    ):
        """Test handling when WebSocket closes during message receive."""
        # Arrange
        mock_ws = MockWebSocketClientProtocol([])
        mock_ws.closed = True
        message_transceiver.connector.ws = mock_ws

        # Act & Assert
        with pytest.raises(EventSubConnectionError) as exc_info:
            await message_transceiver.receive_message()

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    @pytest.mark.asyncio
    async def test_should_handle_json_parse_errors_in_message_processing(
        self, message_coordinator
    ):
        """Test handling of malformed JSON in message processing."""
        # Arrange
        invalid_json_message = WSMessage("text", "invalid json {")

        # Act & Assert - should not raise exception
        result = await message_coordinator.handle_message(invalid_json_message)

        # Should continue processing despite JSON error
        assert result is True

    @pytest.mark.asyncio
    async def test_should_process_session_reconnect_messages(
        self, message_coordinator
    ):
        """Test processing of session reconnect messages."""
        # Arrange
        reconnect_data = {
            "type": "session_reconnect",
            "session": {"id": "new_session_123"}
        }
        message = WSMessage("text", json.dumps(reconnect_data))

        message_coordinator.backend._reconnection_coordinator = Mock()
        message_coordinator.backend._reconnection_coordinator.handle_session_reconnect = AsyncMock()
        message_coordinator.backend._reconnection_coordinator.handle_reconnect = AsyncMock()
        message_coordinator.backend._ws_manager = Mock()
        message_coordinator.backend._ws_manager.update_url = Mock()
        message_coordinator.backend._ws_manager.reconnect = AsyncMock()

        # Act
        result = await message_coordinator.handle_message(message)

        # Assert
        assert result is True
        message_coordinator.backend._reconnection_coordinator.handle_session_reconnect.assert_called_once_with(reconnect_data)

    @pytest.mark.asyncio
    async def test_should_skip_session_keepalive_messages(
        self, message_coordinator
    ):
        """Test that session keepalive messages are ignored."""
        # Arrange
        keepalive_data = {"type": "session_keepalive"}
        message = WSMessage("text", json.dumps(keepalive_data))

        # Act
        result = await message_coordinator.handle_message(message)

        # Assert
        assert result is True
        # Keepalive should not trigger any processing
        message_coordinator.backend._msg_processor.process_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_send_json_messages_correctly(
        self, message_transceiver, mock_websocket_with_messages
    ):
        """Test sending JSON messages through the transceiver."""
        # Arrange
        message_transceiver.connector.ws = mock_websocket_with_messages
        test_data = {"type": "test", "data": "hello"}

        # Act
        await message_transceiver.send_json(test_data)

        # Assert
        assert len(mock_websocket_with_messages.sent_messages) == 1
        sent_message = json.loads(mock_websocket_with_messages.sent_messages[0])
        assert sent_message == test_data

    @pytest.mark.asyncio
    async def test_should_handle_send_errors_gracefully(
        self, message_transceiver
    ):
        """Test graceful handling of send errors."""
        # Arrange
        mock_ws = MockWebSocketClientProtocol()
        mock_ws.closed = True
        message_transceiver.connector.ws = mock_ws

        # Act & Assert
        with pytest.raises(EventSubConnectionError) as exc_info:
            await message_transceiver.send_json({"test": "data"})

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "send"