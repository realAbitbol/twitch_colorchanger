"""
Unit tests for MessageCoordinator.
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import aiohttp

from src.chat.message_coordinator import MessageCoordinator


class TestMessageCoordinator:
    """Test class for MessageCoordinator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_backend = Mock()
        self.coordinator = MessageCoordinator(self.mock_backend)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_handle_message_text_type_processes_message(self):
        """Test handle_message processes TEXT type messages."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = '{"type": "notification", "payload": {}}'

        mock_msg_processor = AsyncMock()
        self.mock_backend._msg_processor = mock_msg_processor
        self.mock_backend._reconnection_coordinator = None

        # Act
        result = await self.coordinator.handle_message(mock_msg)

        # Assert
        assert result is True
        mock_msg_processor.process_message.assert_called_once_with(mock_msg.data)
        assert self.mock_backend._last_activity is not None

    @pytest.mark.asyncio
    async def test_handle_message_session_reconnect_calls_reconnection_coordinator(self):
        """Test handle_message handles session_reconnect messages."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = '{"type": "session_reconnect", "payload": {}}'

        mock_reconnection_coordinator = AsyncMock()
        self.mock_backend._reconnection_coordinator = mock_reconnection_coordinator
        self.mock_backend._msg_processor = None

        # Act
        result = await self.coordinator.handle_message(mock_msg)

        # Assert
        assert result is True
        mock_reconnection_coordinator.handle_session_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_session_reconnect_raises_when_no_coordinator(self):
        """Test handle_message raises AssertionError when no reconnection coordinator for session_reconnect."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = '{"type": "session_reconnect"}'

        self.mock_backend._reconnection_coordinator = None

        # Act & Assert
        with pytest.raises(AssertionError, match="ReconnectionCoordinator not initialized"):
            await self.coordinator.handle_message(mock_msg)

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json_logs_warning(self):
        """Test handle_message logs warning for invalid JSON."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = 'invalid json'

        mock_msg_processor = AsyncMock()
        self.mock_backend._msg_processor = mock_msg_processor

        # Act
        with patch('src.chat.message_coordinator.logging') as mock_logging:
            result = await self.coordinator.handle_message(mock_msg)

        # Assert
        assert result is True
        mock_logging.warning.assert_called_once()
        mock_msg_processor.process_message.assert_called_once_with(mock_msg.data)

    @pytest.mark.asyncio
    async def test_handle_message_closed_type_triggers_reconnect(self):
        """Test handle_message handles CLOSED message type."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.CLOSED

        mock_reconnection_coordinator = AsyncMock()
        mock_reconnection_coordinator.handle_reconnect.return_value = True
        self.mock_backend._reconnection_coordinator = mock_reconnection_coordinator

        # Act
        with patch('src.chat.message_coordinator.logging') as mock_logging:
            result = await self.coordinator.handle_message(mock_msg)

        # Assert
        assert result is True
        mock_logging.info.assert_called_once_with("WebSocket abnormal end")
        mock_reconnection_coordinator.handle_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_error_type_triggers_reconnect(self):
        """Test handle_message handles ERROR message type."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.ERROR

        mock_reconnection_coordinator = AsyncMock()
        mock_reconnection_coordinator.handle_reconnect.return_value = False
        self.mock_backend._reconnection_coordinator = mock_reconnection_coordinator

        # Act
        with patch('src.chat.message_coordinator.logging') as mock_logging:
            result = await self.coordinator.handle_message(mock_msg)

        # Assert
        assert result is False
        mock_logging.info.assert_called_once_with("WebSocket abnormal end")
        mock_reconnection_coordinator.handle_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_closed_raises_when_no_coordinator(self):
        """Test handle_message raises AssertionError for CLOSED when no reconnection coordinator."""
        # Arrange
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.CLOSED

        self.mock_backend._reconnection_coordinator = None

        # Act & Assert
        with pytest.raises(AssertionError, match="ReconnectionCoordinator not initialized"):
            await self.coordinator.handle_message(mock_msg)

    @pytest.mark.asyncio
    async def test_listen_returns_early_when_not_connected(self):
        """Test listen returns early when WebSocket not connected."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_connected = False
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        await self.coordinator.listen()

        # Assert
        # Should return without doing anything

    @pytest.mark.asyncio
    async def test_listen_handles_idle_periods(self):
        """Test listen implements idle optimization."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_connected = True
        mock_ws_manager.receive_message = AsyncMock(side_effect=TimeoutError())
        self.mock_backend._ws_manager = mock_ws_manager
        self.mock_backend._stop_event = Mock()
        self.mock_backend._stop_event.is_set.return_value = False
        self.mock_backend._last_activity = -31  # Very old activity to trigger idle immediately
        self.mock_backend._stale_threshold = 100.0
        self.mock_backend._maybe_verify_subs = AsyncMock()

        # Mock time.monotonic to simulate passage of time
        with patch('src.chat.message_coordinator.time') as mock_time:
            mock_time.monotonic.return_value = 31  # Now is 31, activity was at -31

            # Act
            with patch('asyncio.sleep') as mock_sleep:
                # Stop after first iteration
                self.mock_backend._stop_event.is_set.side_effect = [False, True]

                await self.coordinator.listen()

        # Assert
        mock_sleep.assert_called()  # Should have slept during idle

    @pytest.mark.asyncio
    async def test_listen_processes_messages_normally(self):
        """Test listen processes messages during normal operation."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_connected = True
        mock_msg = Mock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = '{"type": "notification"}'
        mock_ws_manager.receive_message = AsyncMock(return_value=mock_msg)

        mock_msg_processor = AsyncMock()
        self.mock_backend._ws_manager = mock_ws_manager
        self.mock_backend._msg_processor = mock_msg_processor
        self.mock_backend._stop_event = Mock()
        self.mock_backend._stop_event.is_set.return_value = False
        self.mock_backend._last_activity = 0
        self.mock_backend._stale_threshold = 100.0
        self.mock_backend._reconnection_coordinator = None
        self.mock_backend._maybe_verify_subs = AsyncMock()

        # Act
        with patch('src.chat.message_coordinator.time') as mock_time:
            mock_time.monotonic.return_value = 1  # Recent activity

            # Stop after one message
            self.mock_backend._stop_event.is_set.side_effect = [False, True]

            await self.coordinator.listen()

        # Assert
        mock_msg_processor.process_message.assert_called_once_with(mock_msg.data)

    @pytest.mark.asyncio
    async def test_listen_handles_stale_connection(self):
        """Test listen triggers reconnect for stale connections."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_connected = True
        mock_ws_manager.receive_message = AsyncMock(side_effect=TimeoutError())

        mock_reconnection_coordinator = AsyncMock()
        mock_reconnection_coordinator.handle_reconnect.return_value = True

        self.mock_backend._ws_manager = mock_ws_manager
        self.mock_backend._reconnection_coordinator = mock_reconnection_coordinator
        self.mock_backend._stop_event = Mock()
        self.mock_backend._stop_event.is_set.return_value = False
        self.mock_backend._last_activity = 0  # Very old
        self.mock_backend._stale_threshold = 10.0  # Low threshold
        self.mock_backend._maybe_verify_subs = AsyncMock()

        # Act
        with patch('src.chat.message_coordinator.time') as mock_time:
            mock_time.monotonic.return_value = 20  # Past stale threshold

            # Stop after reconnect attempt
            self.mock_backend._stop_event.is_set.side_effect = [False, True]

            with patch('src.chat.message_coordinator.logging') as mock_logging:
                await self.coordinator.listen()

        # Assert
        mock_logging.warning.assert_called()
        mock_reconnection_coordinator.handle_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_listen_handles_general_exceptions(self):
        """Test listen handles general exceptions and triggers reconnect."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_connected = True
        mock_ws_manager.receive_message = AsyncMock(side_effect=Exception("Test error"))

        mock_reconnection_coordinator = AsyncMock()
        mock_reconnection_coordinator.handle_reconnect.return_value = False

        self.mock_backend._ws_manager = mock_ws_manager
        self.mock_backend._reconnection_coordinator = mock_reconnection_coordinator
        self.mock_backend._stop_event = Mock()
        self.mock_backend._stop_event.is_set.return_value = False
        self.mock_backend._last_activity = 0
        self.mock_backend._stale_threshold = 100.0
        self.mock_backend._maybe_verify_subs = AsyncMock()

        # Act
        with patch('src.chat.message_coordinator.time') as mock_time:
            mock_time.monotonic.return_value = 1

            with patch('src.chat.message_coordinator.logging') as mock_logging:
                await self.coordinator.listen()

        # Assert
        mock_logging.warning.assert_called()
        mock_reconnection_coordinator.handle_reconnect.assert_called_once()