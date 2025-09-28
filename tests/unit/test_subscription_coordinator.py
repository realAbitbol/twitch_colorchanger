"""
Unit tests for SubscriptionCoordinator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.chat.subscription_coordinator import SubscriptionCoordinator


class TestSubscriptionCoordinator:
    """Test class for SubscriptionCoordinator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_backend = Mock()
        self.coordinator = SubscriptionCoordinator(self.mock_backend)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_subscribe_primary_channel_returns_true_when_no_sub_manager(self):
        """Test subscribe_primary_channel returns True when no subscription manager."""
        # Arrange
        self.mock_backend._sub_manager = None
        user_ids = {"testchannel": "12345"}

        # Act
        result = await self.coordinator.subscribe_primary_channel(user_ids)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_subscribe_primary_channel_returns_false_when_no_primary_channel(self):
        """Test subscribe_primary_channel returns False when no primary channel set."""
        # Arrange
        self.mock_backend._sub_manager = Mock()
        self.mock_backend._primary_channel = None
        user_ids = {"testchannel": "12345"}

        # Act
        result = await self.coordinator.subscribe_primary_channel(user_ids)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_primary_channel_returns_false_when_channel_not_in_user_ids(self):
        """Test subscribe_primary_channel returns False when primary channel not in user_ids."""
        # Arrange
        self.mock_backend._sub_manager = Mock()
        self.mock_backend._primary_channel = "missingchannel"
        self.mock_backend._user_id = "user123"
        user_ids = {"testchannel": "12345"}

        # Act
        result = await self.coordinator.subscribe_primary_channel(user_ids)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_primary_channel_success(self):
        """Test subscribe_primary_channel succeeds and logs success."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = True
        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._primary_channel = "testchannel"
        self.mock_backend._user_id = "user123"
        self.mock_backend._username = "testuser"
        user_ids = {"testchannel": "12345"}

        # Act
        with patch('src.chat.subscription_coordinator.logging') as mock_logging:
            result = await self.coordinator.subscribe_primary_channel(user_ids)

        # Assert
        assert result is True
        mock_sub_manager.subscribe_channel_chat.assert_called_once_with("12345", "user123")
        mock_logging.info.assert_called_once_with("✅ testuser joined #testchannel")

    @pytest.mark.asyncio
    async def test_subscribe_primary_channel_failure(self):
        """Test subscribe_primary_channel handles subscription failure."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = False
        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._primary_channel = "testchannel"
        self.mock_backend._user_id = "user123"
        user_ids = {"testchannel": "12345"}

        # Act
        result = await self.coordinator.subscribe_primary_channel(user_ids)

        # Assert
        assert result is False
        mock_sub_manager.subscribe_channel_chat.assert_called_once_with("12345", "user123")

    @pytest.mark.asyncio
    async def test_resubscribe_all_channels_returns_true_when_no_managers(self):
        """Test resubscribe_all_channels returns True when no managers available."""
        # Arrange
        self.mock_backend._sub_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._channels = ["channel1", "channel2"]

        # Act
        result = await self.coordinator.resubscribe_all_channels()

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_resubscribe_all_channels_success(self):
        """Test resubscribe_all_channels succeeds for all channels."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = True
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {"channel1": "111", "channel2": "222"}

        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = ["channel1", "channel2"]
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"
        self.mock_backend._user_id = "user123"

        # Act
        result = await self.coordinator.resubscribe_all_channels()

        # Assert
        assert result is True
        assert mock_channel_resolver.resolve_user_ids.call_count == 2
        assert mock_sub_manager.subscribe_channel_chat.call_count == 2

    @pytest.mark.asyncio
    async def test_resubscribe_all_channels_partial_failure(self):
        """Test resubscribe_all_channels handles partial failures."""
        # Arrange
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {"channel1": "111", "channel2": "222"}

        self.mock_backend._sub_manager = AsyncMock()
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = ["channel1", "channel2"]
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"
        self.mock_backend._user_id = "user123"

        # Mock _subscribe_channel_with_retry to return True for channel1, False for channel2
        with patch.object(self.coordinator, '_subscribe_channel_with_retry') as mock_retry:
            mock_retry.side_effect = [True, False]

            # Act
            result = await self.coordinator.resubscribe_all_channels()

        # Assert
        assert result is False
        assert mock_retry.call_count == 2

    @pytest.mark.asyncio
    async def test_resubscribe_all_channels_resolution_failure(self):
        """Test resubscribe_all_channels handles channel resolution failures."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {"channel1": "111"}  # missing channel2

        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = ["channel1", "channel2"]
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"

        # Act
        result = await self.coordinator.resubscribe_all_channels()

        # Assert
        assert result is False
        mock_sub_manager.subscribe_channel_chat.assert_called_once()  # only for channel1

    @pytest.mark.asyncio
    async def test_join_channel_already_joined(self):
        """Test join_channel returns True when already joined."""
        # Arrange
        self.mock_backend._channels = ["existingchannel"]

        # Act
        result = await self.coordinator.join_channel("#existingchannel")

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_join_channel_success(self):
        """Test join_channel succeeds and adds channel to list."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = True
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {"newchannel": "999"}

        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = []
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"
        self.mock_backend._user_id = "user123"
        self.mock_backend._username = "testuser"

        # Act
        with patch('src.chat.subscription_coordinator.logging') as mock_logging:
            result = await self.coordinator.join_channel("newchannel")

        # Assert
        assert result is True
        assert "newchannel" in self.mock_backend._channels
        mock_logging.info.assert_called_once_with("✅ testuser joined #newchannel")

    @pytest.mark.asyncio
    async def test_join_channel_resolution_failure(self):
        """Test join_channel fails when channel resolution fails."""
        # Arrange
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {}  # empty result

        self.mock_backend._sub_manager = Mock()
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = []
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"

        # Act
        result = await self.coordinator.join_channel("newchannel")

        # Assert
        assert result is False
        assert "newchannel" not in self.mock_backend._channels

    @pytest.mark.asyncio
    async def test_join_channel_subscription_failure(self):
        """Test join_channel fails when subscription fails."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = False
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.return_value = {"newchannel": "999"}

        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = []
        self.mock_backend._token = "token123"
        self.mock_backend._client_id = "client123"
        self.mock_backend._user_id = "user123"

        # Act
        result = await self.coordinator.join_channel("newchannel")

        # Assert
        assert result is False
        assert "newchannel" not in self.mock_backend._channels

    @pytest.mark.asyncio
    async def test_join_channel_handles_exceptions(self):
        """Test join_channel handles exceptions gracefully."""
        # Arrange
        mock_channel_resolver = AsyncMock()
        mock_channel_resolver.resolve_user_ids.side_effect = Exception("Resolution error")

        self.mock_backend._sub_manager = Mock()
        self.mock_backend._channel_resolver = mock_channel_resolver
        self.mock_backend._channels = []

        # Act
        with patch('src.chat.subscription_coordinator.logging') as mock_logging:
            result = await self.coordinator.join_channel("newchannel")

        # Assert
        assert result is False
        mock_logging.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_channel_with_retry_no_sub_manager(self):
        """Test _subscribe_channel_with_retry returns None when no sub manager."""
        # Arrange
        self.mock_backend._sub_manager = None

        # Act
        result = await self.coordinator._subscribe_channel_with_retry("123", "testchannel")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_channel_with_retry_success(self):
        """Test _subscribe_channel_with_retry succeeds on first attempt."""
        # Arrange
        mock_sub_manager = AsyncMock()
        mock_sub_manager.subscribe_channel_chat.return_value = True
        self.mock_backend._sub_manager = mock_sub_manager
        self.mock_backend._user_id = "user123"

        # Act
        result = await self.coordinator._subscribe_channel_with_retry("123", "testchannel")

        # Assert
        assert result is True
        mock_sub_manager.subscribe_channel_chat.assert_called_once_with("123", "user123")

    @pytest.mark.asyncio
    async def test_subscribe_channel_with_retry_handles_exceptions(self):
        """Test _subscribe_channel_with_retry handles subscription exceptions."""
        # Arrange
        self.mock_backend._sub_manager = AsyncMock()
        self.mock_backend._user_id = "user123"

        # Mock retry_async to return False on exception
        with patch('src.chat.subscription_coordinator.retry_async', return_value=False):
            with patch('src.chat.subscription_coordinator.logging') as mock_logging:
                result = await self.coordinator._subscribe_channel_with_retry("123", "testchannel")

        # Assert
        assert result is False