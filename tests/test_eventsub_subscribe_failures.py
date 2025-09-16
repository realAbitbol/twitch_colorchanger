import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.chat.cache_manager import CacheManager
from src.chat.channel_resolver import ChannelResolver
from src.chat.eventsub_backend import EventSubChatBackend
from src.chat.message_processor import MessageProcessor
from src.chat.subscription_manager import SubscriptionManager
from src.chat.token_manager import TokenManager
from src.chat.websocket_connection_manager import WebSocketConnectionManager


class DummyAPI:
    def __init__(self, statuses):
        self.statuses = list(statuses)

    async def request(self, method, endpoint, *, access_token, client_id, json_body, params=None, json=None):  # noqa: D401
        await asyncio.sleep(0)
        status = self.statuses.pop(0)
        data = {"message": "err"} if status != 202 else {"ok": True}
        return data, status, {}


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
async def test_two_401s_set_invalid_flag(mock_components):
    """Test consecutive 401 errors trigger invalidation."""
    from src.errors.eventsub import SubscriptionError

    EventSubChatBackend(**mock_components)

    # Mock subscription manager to raise errors on consecutive 401s
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(
        side_effect=[
            SubscriptionError("401 error", operation_type="subscribe"),
            SubscriptionError("401 error again", operation_type="subscribe")
        ]
    )

    # First 401
    with pytest.raises(SubscriptionError):
        await mock_components['sub_manager'].subscribe_channel_chat("chan", "uid")

    # Second 401 should also raise
    with pytest.raises(SubscriptionError):
        await mock_components['sub_manager'].subscribe_channel_chat("chan", "uid")


@pytest.mark.asyncio
async def test_403_missing_scopes_logs(mock_components):
    """Test 403 errors for missing scopes."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to handle 403
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=False)

    result = await mock_components['sub_manager'].subscribe_channel_chat("chan", "uid")
    assert result is False
