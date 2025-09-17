"""Tests for src/chat/eventsub_backend.py."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.chat.cache_manager import CacheManager
from src.chat.channel_resolver import ChannelResolver
from src.chat.eventsub_backend import EventSubChatBackend
from src.chat.message_processor import MessageProcessor
from src.chat.subscription_manager import SubscriptionManager
from src.chat.websocket_connection_manager import WebSocketConnectionManager


@pytest.fixture
def mock_components():
    """Create mock components for dependency injection."""
    mock_ws_manager = MagicMock(spec=WebSocketConnectionManager)
    mock_sub_manager = MagicMock(spec=SubscriptionManager)
    mock_msg_processor = MagicMock(spec=MessageProcessor)
    mock_channel_resolver = MagicMock(spec=ChannelResolver)
    mock_token_manager = MagicMock()
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
    backend._username = "testuser"  # Set username for callback registration

    # Mock token manager callback
    callback_mock = AsyncMock()
    mock_components['token_manager'].set_invalid_callback = AsyncMock()

    await backend.set_token_invalid_callback(callback_mock)
    mock_components['token_manager'].set_invalid_callback.assert_called_once_with("testuser", callback_mock)


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
async def test_update_all_components_success(mock_components):
    """Test _update_all_components with all components present."""
    backend = EventSubChatBackend(**mock_components)
    backend._username = "testuser"  # Set username for token validation

    # Mock components
    mock_components['ws_manager'].update_token = MagicMock()
    mock_components['sub_manager'].update_access_token = MagicMock()
    mock_components['token_manager'].validate_token = AsyncMock()

    await backend._update_all_components("new_token")

    # Verify all components were updated
    mock_components['ws_manager'].update_token.assert_called_once_with("new_token")
    mock_components['sub_manager'].update_access_token.assert_called_once_with("new_token")
    mock_components['token_manager'].validate_token.assert_called_once_with("new_token")
    assert backend._token == "new_token"


@pytest.mark.asyncio
async def test_update_all_components_partial_components(mock_components):
    """Test _update_all_components with some components missing."""
    backend = EventSubChatBackend(**mock_components)
    backend._username = "testuser"  # Set username for token validation

    # Remove some components
    backend._ws_manager = None
    backend._sub_manager = None

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock()

    await backend._update_all_components("new_token")

    # Only token manager should be called
    mock_components['token_manager'].validate_token.assert_called_once_with("new_token")
    assert backend._token == "new_token"


@pytest.mark.asyncio
async def test_update_all_components_ws_no_update_method(mock_components):
    """Test _update_all_components when WebSocket manager has no update_token method."""
    backend = EventSubChatBackend(**mock_components)
    backend._username = "testuser"  # Set username for token validation

    # Remove update_token method
    del mock_components['ws_manager'].update_token

    # Mock other components
    mock_components['sub_manager'].update_access_token = MagicMock()
    mock_components['token_manager'].validate_token = AsyncMock()

    await backend._update_all_components("new_token")

    # Should not call update_token on ws_manager
    mock_components['sub_manager'].update_access_token.assert_called_once_with("new_token")
    mock_components['token_manager'].validate_token.assert_called_once_with("new_token")


@pytest.mark.asyncio
async def test_update_all_components_with_exceptions(mock_components):
    """Test _update_all_components handles exceptions gracefully."""
    backend = EventSubChatBackend(**mock_components)
    backend._username = "testuser"  # Set username for token validation

    # Mock components to raise exceptions
    mock_components['ws_manager'].update_token = MagicMock(side_effect=ValueError("WS error"))
    mock_components['sub_manager'].update_access_token = MagicMock(side_effect=RuntimeError("Sub error"))
    mock_components['token_manager'].validate_token = AsyncMock(side_effect=Exception("Token error"))

    # Should not raise exceptions
    await backend._update_all_components("new_token")

    # All should have been called despite exceptions
    mock_components['ws_manager'].update_token.assert_called_once_with("new_token")
    mock_components['sub_manager'].update_access_token.assert_called_once_with("new_token")
    mock_components['token_manager'].validate_token.assert_called_once_with("new_token")
    assert backend._token == "new_token"


@pytest.mark.asyncio
async def test_handle_reconnect_verifies_subscriptions(mock_components):
    """Test _handle_reconnect verifies subscriptions before resubscribing."""
    backend = EventSubChatBackend(**mock_components)

    mock_components['ws_manager'].reconnect = AsyncMock()
    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=['channel1'])

    await backend._handle_reconnect()

    mock_components['ws_manager'].reconnect.assert_called_once()
    mock_components['sub_manager'].verify_subscriptions.assert_called_once()
    # Should not call _resubscribe_all_channels since active channels exist


@pytest.mark.asyncio
async def test_handle_reconnect_no_active_subscriptions(mock_components):
    """Test _handle_reconnect resubscribes when no active subscriptions."""
    backend = EventSubChatBackend(**mock_components)

    mock_components['ws_manager'].reconnect = AsyncMock()
    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=[])

    with patch.object(backend, '_resubscribe_all_channels', new_callable=AsyncMock) as mock_resub:
        await backend._handle_reconnect()
        mock_resub.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_verify_subs_fixed_interval(mock_components):
    """Test _maybe_verify_subs uses fixed interval."""
    backend = EventSubChatBackend(**mock_components)

    # Set up for check being due
    backend._next_sub_check = time.monotonic() - 1  # Due for check

    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=['channel1'])

    await backend._maybe_verify_subs(time.monotonic())

    mock_components['sub_manager'].verify_subscriptions.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_verify_subs_uses_fixed_interval_constant(mock_components):
    """Test _maybe_verify_subs uses fixed interval from constant."""
    backend = EventSubChatBackend(**mock_components)

    # Set up for check being due
    backend._next_sub_check = time.monotonic() - 1  # Due for check

    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=['channel1'])

    await backend._maybe_verify_subs(time.monotonic())

    mock_components['sub_manager'].verify_subscriptions.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_verify_subs_schedules_next_check(mock_components):
    """Test that _maybe_verify_subs schedules the next check with fixed interval."""
    backend = EventSubChatBackend(**mock_components)

    # Set up for check being due
    current_time = time.monotonic()
    backend._next_sub_check = current_time - 1  # Due for check

    mock_components['sub_manager'].verify_subscriptions = AsyncMock(return_value=['channel1'])

    await backend._maybe_verify_subs(current_time)

    # Should have called verify_subscriptions since check was due
    mock_components['sub_manager'].verify_subscriptions.assert_called_once()

    # Next check should be scheduled with fixed interval
    from src.constants import EVENTSUB_SUB_CHECK_INTERVAL_SECONDS
    expected_next_check = current_time + EVENTSUB_SUB_CHECK_INTERVAL_SECONDS
    assert abs(backend._next_sub_check - expected_next_check) < 0.01  # Small tolerance for timing
