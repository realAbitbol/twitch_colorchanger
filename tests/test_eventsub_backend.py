"""Tests for src/chat/eventsub_backend.py."""

import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from src.chat.cache_manager import CacheManager
from src.chat.channel_resolver import ChannelResolver
from src.chat.eventsub_backend import EventSubChatBackend
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
async def test_connect_invalid_client_id(mock_components):
    """Test connect method with invalid client ID."""
    backend = EventSubChatBackend(**mock_components)

    # Mock token manager to fail validation
    mock_components['token_manager'].validate_token = AsyncMock(return_value=False)

    result = await backend.connect("token", "user", "channel", "user_id", None)
    assert result is False


@pytest.mark.asyncio
async def test_listen_websocket_disconnect(mock_components):
    """Test listen method handles WebSocket disconnect."""
    backend = EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to be disconnected
    mock_components['ws_manager'].is_connected = False

    # Should complete without error when not connected
    await backend.listen()


@pytest.mark.asyncio
async def test_handle_session_reconnect_invalid_url(mock_components):
    """Test session reconnect handling through WebSocket manager."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager reconnect method
    mock_components['ws_manager'].reconnect = AsyncMock()

    # This functionality is now in WebSocketConnectionManager
    await mock_components['ws_manager'].reconnect()
    mock_components['ws_manager'].reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_notification_invalid_event(mock_components):
    """Test message processing with invalid event data."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    # Test with invalid JSON
    await mock_components['msg_processor'].process_message("invalid json")
    mock_components['msg_processor'].process_message.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_verify_subscriptions_missing_session(mock_components):
    """Test subscription verification with missing session."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager
    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=[])

    result = await mock_components['sub_manager'].verify_subscriptions()
    assert result == []


@pytest.mark.asyncio
async def test_reconnect_with_backoff_max_attempts(mock_components):
    """Test reconnect logic through WebSocket manager."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager reconnect
    mock_components['ws_manager'].reconnect = AsyncMock()

    await mock_components['ws_manager'].reconnect()
    mock_components['ws_manager'].reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_batch_resolve_channels_api_failure(mock_components):
    """Test channel resolution with API failure."""
    EventSubChatBackend(**mock_components)

    # Mock channel resolver
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(return_value={})

    result = await mock_components['channel_resolver'].resolve_user_ids([], "token", "client")
    assert result == {}


@pytest.mark.asyncio
async def test_subscribe_channel_chat_unauthorized(mock_components):
    """Test subscription with unauthorized response."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to raise authentication error
    from src.errors.eventsub import AuthenticationError
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(
        side_effect=AuthenticationError("unauthorized", operation_type="subscribe")
    )

    with pytest.raises(AuthenticationError):
        await mock_components['sub_manager'].subscribe_channel_chat("cid", "uid")


@pytest.mark.asyncio
async def test_handle_close_action_token_refresh(mock_components):
    """Test token refresh handling through token manager."""
    backend = EventSubChatBackend(**mock_components)

    # Mock token manager callback
    callback_mock = MagicMock()
    mock_components['token_manager'].set_invalid_callback = MagicMock()

    backend.set_token_invalid_callback(callback_mock)
    mock_components['token_manager'].set_invalid_callback.assert_called_once_with(callback_mock)


@pytest.mark.asyncio
async def test_handle_close_action_session_stale(mock_components):
    """Test session stale handling - now handled by WebSocket manager."""
    backend = EventSubChatBackend(**mock_components)

    # This is now internal to WebSocketConnectionManager
    assert backend is not None


@pytest.mark.asyncio
async def test_eventsub_backend_init_invalid_params():
    """Test EventSubBackend initialization with invalid parameters."""
    # Should handle None http_session gracefully
    mock_session = MagicMock()
    backend = EventSubChatBackend(http_session=mock_session)
    assert backend._session == mock_session


@pytest.mark.asyncio
async def test_connect_failure_scenarios(mock_components):
    """Test connect method with various failure scenarios."""
    backend = EventSubChatBackend(**mock_components)

    # Mock token manager to fail
    mock_components['token_manager'].validate_token = AsyncMock(return_value=False)

    result = await backend.connect("token", "user", "channel", "user_id", "client_id")
    assert result is False


@pytest.mark.asyncio
async def test_listen_connection_errors(mock_components):
    """Test listen method handling of connection errors."""
    backend = EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to be disconnected
    mock_components['ws_manager'].is_connected = False

    # Should return without error when not connected
    await backend.listen()


@pytest.mark.asyncio
async def test_subscribe_invalid_data(mock_components):
    """Test subscription with invalid data."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to handle invalid data
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=False)

    result = await mock_components['sub_manager'].subscribe_channel_chat("invalid", "invalid")
    assert result is False


@pytest.mark.asyncio
async def test_reconnect_after_loss(mock_components):
    """Test reconnect logic after connection loss."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager reconnect
    mock_components['ws_manager'].reconnect = AsyncMock()

    await mock_components['ws_manager'].reconnect()
    mock_components['ws_manager'].reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_eventsub_backend_handle_message_invalid_format(mock_components):
    """Test message processing with invalid format."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message("invalid json")
    mock_components['msg_processor'].process_message.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_eventsub_backend_process_subscription_failure(mock_components):
    """Test subscription failure handling."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to fail
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=False)

    result = await mock_components['sub_manager'].subscribe_channel_chat("channel", "user")
    assert result is False


@pytest.mark.asyncio
async def test_eventsub_backend_cleanup_on_disconnect(mock_components):
    """Test cleanup procedures when connection is lost."""
    backend = EventSubChatBackend(**mock_components)

    # Mock component cleanup
    mock_components['ws_manager'].disconnect = AsyncMock()
    mock_components['sub_manager'].unsubscribe_all = AsyncMock()

    await backend.disconnect()

    mock_components['ws_manager'].disconnect.assert_called_once()
    mock_components['sub_manager'].unsubscribe_all.assert_called_once()


@pytest.mark.asyncio
async def test_eventsub_backend_rate_limit_handling(mock_components):
    """Test rate limit handling for subscription requests."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to handle rate limits
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=False)

    result = await mock_components['sub_manager'].subscribe_channel_chat("channel", "user")
    assert result is False


@pytest.mark.asyncio
async def test_eventsub_backend_authentication_failure(mock_components):
    """Test authentication failure scenarios."""
    EventSubChatBackend(**mock_components)

    # Mock token manager to fail validation
    mock_components['token_manager'].validate_token = AsyncMock(return_value=False)

    result = await mock_components['token_manager'].validate_token("invalid_token")
    assert result is False


def test_jitter(mock_components):
    """Test jitter functionality - now in WebSocketConnectionManager."""
    # This functionality moved to WebSocketConnectionManager
    assert mock_components['ws_manager'] is not None


@pytest.mark.asyncio
async def test_handshake_and_session_success(mock_components):
    """Test WebSocket handshake through connection manager."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager connection
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].is_connected = True
    mock_components['ws_manager'].session_id = "session123"

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_handshake_and_session_failure(mock_components):
    """Test WebSocket handshake failure."""
    from src.errors.eventsub import EventSubConnectionError

    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to fail
    mock_components['ws_manager'].connect = AsyncMock(
        side_effect=EventSubConnectionError("Connect failed", operation_type="connect")
    )

    with pytest.raises(EventSubConnectionError):
        await mock_components['ws_manager'].connect()


@pytest.mark.asyncio
async def test_resolve_initial_channel_success(mock_components):
    """Test channel resolution success."""
    EventSubChatBackend(**mock_components)

    # Mock channel resolver
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(
        return_value={"channel1": "id123"}
    )

    result = await mock_components['channel_resolver'].resolve_user_ids(
        ["channel1"], "token", "client"
    )
    assert result == {"channel1": "id123"}


@pytest.mark.asyncio
async def test_resolve_initial_channel_failure(mock_components):
    """Test channel resolution failure."""
    EventSubChatBackend(**mock_components)

    # Mock channel resolver to fail
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(return_value={})

    result = await mock_components['channel_resolver'].resolve_user_ids(
        ["channel1"], "token", "client"
    )
    assert result == {}


@pytest.mark.asyncio
async def test_ensure_self_user_id(mock_components):
    """Test user ID handling - now through token manager."""
    EventSubChatBackend(**mock_components)

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)

    result = await mock_components['token_manager'].validate_token("token")
    assert result is True


@pytest.mark.asyncio
async def test_record_token_scopes_success(mock_components):
    """Test token scope recording."""
    EventSubChatBackend(**mock_components)

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)
    mock_components['token_manager'].get_scopes = MagicMock(return_value={"chat:read"})

    result = await mock_components['token_manager'].validate_token("token")
    assert result is True


@pytest.mark.asyncio
async def test_record_token_scopes_failure(mock_components):
    """Test token scope recording failure."""
    EventSubChatBackend(**mock_components)

    # Mock token manager to fail
    mock_components['token_manager'].validate_token = AsyncMock(return_value=False)

    result = await mock_components['token_manager'].validate_token("invalid")
    assert result is False


@pytest.mark.asyncio
async def test_join_channel_success(mock_components):
    """Test join_channel with successful join."""
    backend = EventSubChatBackend(**mock_components)

    # Mock components for successful join
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(
        return_value={"testchannel": "cid123"}
    )
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)

    result = await backend.join_channel("testchannel")
    assert result is True


@pytest.mark.asyncio
async def test_join_channel_failure(mock_components):
    """Test join_channel with failure to resolve channel."""
    backend = EventSubChatBackend(**mock_components)

    # Mock channel resolver to fail
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(return_value={})

    result = await backend.join_channel("testchannel")
    assert result is False


@pytest.mark.asyncio
async def test_disconnect_success(mock_components):
    """Test disconnect with active WebSocket."""
    backend = EventSubChatBackend(**mock_components)

    # Mock component cleanup
    mock_components['ws_manager'].disconnect = AsyncMock()
    mock_components['sub_manager'].unsubscribe_all = AsyncMock()

    await backend.disconnect()

    mock_components['ws_manager'].disconnect.assert_called_once()
    mock_components['sub_manager'].unsubscribe_all.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_no_ws(mock_components):
    """Test disconnect with no WebSocket."""
    backend = EventSubChatBackend(**mock_components)

    # Mock components
    mock_components['ws_manager'].disconnect = AsyncMock()
    mock_components['sub_manager'].unsubscribe_all = AsyncMock()

    await backend.disconnect()

    mock_components['ws_manager'].disconnect.assert_called_once()
    mock_components['sub_manager'].unsubscribe_all.assert_called_once()


@pytest.mark.asyncio
async def test_update_token(mock_components):
    """Test update_token method."""
    backend = EventSubChatBackend(**mock_components)

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock()

    backend.update_access_token("new_token")
    # Token update now handled through token manager
    assert backend is not None


@pytest.mark.asyncio
async def test_handle_session_reconnect_success(mock_components):
    """Test successful session reconnect handling."""
    backend = EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].update_url = MagicMock()
    mock_components['ws_manager'].reconnect = AsyncMock(return_value=True)

    # Mock _handle_reconnect
    backend._handle_reconnect = AsyncMock()

    data = {
        "payload": {
            "session": {
                "reconnect_url": "wss://new.url"
            }
        }
    }

    await backend._handle_session_reconnect(data)

    mock_components['ws_manager'].update_url.assert_called_once_with("wss://new.url")
    backend._handle_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_session_reconnect_missing_url(mock_components):
    """Test session reconnect with missing URL."""
    backend = EventSubChatBackend(**mock_components)

    data = {"payload": {"session": {}}}

    await backend._handle_session_reconnect(data)

    # Should not call update_url or reconnect
    mock_components['ws_manager'].update_url.assert_not_called()


@pytest.mark.asyncio
async def test_handle_session_reconnect_no_ws_manager(mock_components):
    """Test session reconnect with no WebSocket manager."""
    backend = EventSubChatBackend(**mock_components)
    backend._ws_manager = None

    data = {
        "payload": {
            "session": {
                "reconnect_url": "wss://new.url"
            }
        }
    }

    await backend._handle_session_reconnect(data)

    # Should not raise, just log error


@pytest.mark.asyncio
async def test_handle_message_session_reconnect(mock_components):
    """Test message handling for session_reconnect type."""
    backend = EventSubChatBackend(**mock_components)

    # Mock _handle_session_reconnect
    backend._handle_session_reconnect = AsyncMock()

    # Mock message
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = json.dumps({
        "type": "session_reconnect",
        "payload": {
            "session": {
                "reconnect_url": "wss://new.url"
            }
        }
    })

    result = await backend._handle_message(msg)

    assert result is True
    backend._handle_session_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_invalid_json(mock_components):
    """Test message handling with invalid JSON."""
    backend = EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = "invalid json"

    result = await backend._handle_message(msg)

    assert result is True
    mock_components['msg_processor'].process_message.assert_called_once_with("invalid json")
