"""
Unit tests for ReconnectionCoordinator.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from src.chat.reconnection_coordinator import ReconnectionCoordinator


class TestReconnectionCoordinator:
    """Test class for ReconnectionCoordinator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_backend = Mock()
        self.coordinator = ReconnectionCoordinator(self.mock_backend)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_handle_session_reconnect_success(self):
        """Test handle_session_reconnect updates URL and triggers reconnect."""
        # Arrange
        data = {
            "payload": {
                "session": {
                    "reconnect_url": "wss://new-url.com"
                }
            }
        }

        mock_ws_manager = Mock()
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        with patch.object(self.coordinator, 'handle_reconnect', new_callable=AsyncMock) as mock_reconnect, \
             patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            await self.coordinator.handle_session_reconnect(data)

        # Assert
        mock_ws_manager.update_url.assert_called_once_with("wss://new-url.com")
        mock_reconnect.assert_called_once()
        mock_logging.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_session_reconnect_missing_url(self):
        """Test handle_session_reconnect logs error when reconnect_url is missing."""
        # Arrange
        data = {"payload": {"session": {}}}

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            await self.coordinator.handle_session_reconnect(data)

        # Assert
        mock_logging.error.assert_called_once_with("Session reconnect message missing reconnect_url")

    @pytest.mark.asyncio
    async def test_handle_session_reconnect_no_ws_manager(self):
        """Test handle_session_reconnect logs error when no WebSocket manager."""
        # Arrange
        data = {
            "payload": {
                "session": {
                    "reconnect_url": "wss://new-url.com"
                }
            }
        }

        self.mock_backend._ws_manager = None

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            await self.coordinator.handle_session_reconnect(data)

        # Assert
        mock_logging.error.assert_called_once_with("No WebSocket manager available for session reconnect")

    @pytest.mark.asyncio
    async def test_handle_session_reconnect_handles_exceptions(self):
        """Test handle_session_reconnect handles exceptions gracefully."""
        # Arrange
        data = {
            "payload": {
                "session": {
                    "reconnect_url": "wss://new-url.com"
                }
            }
        }

        mock_ws_manager = Mock()
        mock_ws_manager.update_url.side_effect = Exception("Update failed")
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            await self.coordinator.handle_session_reconnect(data)

        # Assert
        mock_logging.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reconnect_no_ws_manager(self):
        """Test handle_reconnect returns False when no WebSocket manager."""
        # Arrange
        self.mock_backend._ws_manager = None

        # Act
        result = await self.coordinator.handle_reconnect()

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_reconnect_reconnect_fails(self):
        """Test handle_reconnect returns False when reconnect fails."""
        # Arrange
        mock_ws_manager = AsyncMock()
        mock_ws_manager.reconnect.return_value = False
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        result = await self.coordinator.handle_reconnect()

        # Assert
        assert result is False
        mock_ws_manager.reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reconnect_health_validation_fails(self):
        """Test handle_reconnect returns False when health validation fails."""
        # Arrange
        mock_ws_manager = AsyncMock()
        mock_ws_manager.reconnect.return_value = True
        self.mock_backend._ws_manager = mock_ws_manager

        with patch.object(self.coordinator, 'validate_connection_health', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            # Act
            result = await self.coordinator.handle_reconnect()

        # Assert
        assert result is False
        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reconnect_success(self):
        """Test handle_reconnect succeeds and performs all operations."""
        # Arrange
        mock_ws_manager = AsyncMock()
        mock_ws_manager.reconnect.return_value = True
        mock_ws_manager.session_id = "new_session_123"
        self.mock_backend._ws_manager = mock_ws_manager

        mock_sub_manager = Mock()
        mock_sub_manager.update_session_id = AsyncMock()
        mock_sub_manager.unsubscribe_all = AsyncMock()
        self.mock_backend._sub_manager = mock_sub_manager

        mock_subscription_coordinator = AsyncMock()
        mock_subscription_coordinator.resubscribe_all_channels.return_value = True
        self.mock_backend._subscription_coordinator = mock_subscription_coordinator

        with patch.object(self.coordinator, 'validate_connection_health', AsyncMock(return_value=True)) as mock_validate, \
              patch('src.chat.reconnection_coordinator.logging'):
            # Act
            result = await self.coordinator.handle_reconnect()

        # Assert
        assert result is True
        mock_ws_manager.reconnect.assert_called_once()
        mock_validate.assert_called_once()
        mock_sub_manager.update_session_id.assert_called_once_with("new_session_123")
        mock_sub_manager.unsubscribe_all.assert_called_once()
        mock_subscription_coordinator.resubscribe_all_channels.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reconnect_handles_exceptions(self):
        """Test handle_reconnect handles various exceptions."""
        # Arrange
        mock_ws_manager = AsyncMock()
        mock_ws_manager.reconnect.side_effect = Exception("Reconnect failed")
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            result = await self.coordinator.handle_reconnect()

        # Assert
        assert result is False
        mock_logging.error.assert_called()

    @pytest.mark.asyncio
    async def test_validate_connection_health_no_ws_manager(self):
        """Test validate_connection_health returns False when no WebSocket manager."""
        # Arrange
        self.mock_backend._ws_manager = None

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            result = await self.coordinator.validate_connection_health()

        # Assert
        assert result is False
        mock_logging.error.assert_called_once_with("No WebSocket manager for health validation")

    @pytest.mark.asyncio
    async def test_validate_connection_health_unhealthy_manager(self):
        """Test validate_connection_health returns False when manager reports unhealthy."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_healthy.return_value = False
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        with patch('src.chat.reconnection_coordinator.logging') as mock_logging:
            result = await self.coordinator.validate_connection_health()

        # Assert
        assert result is False
        mock_logging.error.assert_called_once_with("WebSocket manager reports unhealthy connection")

    @pytest.mark.asyncio
    async def test_validate_connection_health_success(self):
        """Test validate_connection_health succeeds when WebSocket manager is healthy."""
        # Arrange
        mock_ws_manager = Mock()
        mock_ws_manager.is_healthy.return_value = True
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        result = await self.coordinator.validate_connection_health()

        # Assert
        assert result is True

