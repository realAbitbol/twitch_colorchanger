"""
Unit tests for MessageTransceiver.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.chat.message_transceiver import MessageTransceiver
from src.errors.eventsub import EventSubConnectionError


class TestMessageTransceiver:
    """Test class for MessageTransceiver functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.connector = Mock()
        self.last_activity = 0.0
        self.transceiver = MessageTransceiver(self.connector, self.last_activity)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_send_json_success(self):
        """Test send_json sends data successfully."""
        mock_ws = Mock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        self.connector.ws = mock_ws

        data = {"type": "test", "data": "value"}

        await self.transceiver.send_json(data)

        mock_ws.send_json.assert_called_once_with(data)
        assert self.transceiver.last_activity != 0.0  # Should be updated

    @pytest.mark.asyncio
    async def test_send_json_raises_when_not_connected(self):
        """Test send_json raises when WebSocket not connected."""
        self.connector.ws = None

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.transceiver.send_json({"test": "data"})

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "send"

    @pytest.mark.asyncio
    async def test_send_json_raises_when_connection_closed(self):
        """Test send_json raises when WebSocket connection is closed."""
        mock_ws = Mock()
        mock_ws.closed = True
        self.connector.ws = mock_ws

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.transceiver.send_json({"test": "data"})

        assert "WebSocket not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_receive_message_success(self):
        """Test receive_message receives message successfully."""
        mock_ws = Mock()
        mock_ws.closed = False
        mock_msg = Mock()
        mock_ws.receive = AsyncMock(return_value=mock_msg)
        self.connector.ws = mock_ws

        result = await self.transceiver.receive_message()

        assert result == mock_msg
        assert self.transceiver.last_activity != 0.0  # Should be updated

    @pytest.mark.asyncio
    async def test_receive_message_raises_when_not_connected(self):
        """Test receive_message raises when WebSocket not connected."""
        self.connector.ws = None

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.transceiver.receive_message()

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    @pytest.mark.asyncio
    async def test_receive_message_raises_on_timeout(self):
        """Test receive_message raises on timeout."""
        mock_ws = Mock()
        mock_ws.closed = False
        mock_ws.receive = AsyncMock(side_effect=TimeoutError())
        self.connector.ws = mock_ws

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.transceiver.receive_message()

        assert "WebSocket receive timeout" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    @pytest.mark.asyncio
    async def test_receive_message_raises_on_general_error(self):
        """Test receive_message raises on general errors."""
        mock_ws = Mock()
        mock_ws.closed = False
        mock_ws.receive = AsyncMock(side_effect=Exception("Receive failed"))
        self.connector.ws = mock_ws

        with pytest.raises(EventSubConnectionError) as exc_info:
            await self.transceiver.receive_message()

        assert "WebSocket receive failed" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"
