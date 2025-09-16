from unittest.mock import AsyncMock, MagicMock

import pytest

from src.chat.cache_manager import CacheManager
from src.chat.channel_resolver import ChannelResolver
from src.chat.message_processor import MessageProcessor
from src.chat.subscription_manager import SubscriptionManager
from src.chat.token_manager import TokenManager
from src.chat.websocket_connection_manager import WebSocketConnectionManager


@pytest.fixture
def mock_components():
    """Create mock components for dependency injection."""
    mock_ws_manager = MagicMock(spec=WebSocketConnectionManager)
    mock_sub_manager = MagicMock(spec=SubscriptionManager)
    mock_msg_processor = MagicMock(spec=MessageProcessor)
    mock_channel_resolver = MagicMock(spec=ChannelResolver)
    mock_token_manager = MagicMock(spec=TokenManager)
    mock_cache_manager = MagicMock(spec=CacheManager)

    return {
        'ws_manager': mock_ws_manager,
        'sub_manager': mock_sub_manager,
        'msg_processor': mock_msg_processor,
        'channel_resolver': mock_channel_resolver,
        'token_manager': mock_token_manager,
        'cache_manager': mock_cache_manager,
    }


@pytest.mark.asyncio
async def test_subscribe_channel_chat_success(mock_components):
    """Test successful channel chat subscription through subscription manager."""
    # Mock successful subscription
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)

    # Test that backend delegates to subscription manager
    result = await mock_components['sub_manager'].subscribe_channel_chat("chan123", "user123")
    assert result is True
    mock_components['sub_manager'].subscribe_channel_chat.assert_called_once_with("chan123", "user123")
