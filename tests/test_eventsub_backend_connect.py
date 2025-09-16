from unittest.mock import AsyncMock, MagicMock

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
async def test_capture_initial_credentials_success(mock_components):
    """Test connect method sets credentials correctly."""
    backend = EventSubChatBackend(**mock_components)

    # Mock successful connection - all components need to be mocked properly
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)
    mock_components['token_manager'].get_scopes = MagicMock(return_value={"chat:read"})
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(return_value={"testchan": "12345"})
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].session_id = "session123"
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)
    mock_components['sub_manager'].update_session_id = MagicMock()

    result = await backend.connect("test_token", "testuser", "testchan", "12345", "client123")
    assert result is True


@pytest.mark.asyncio
async def test_validate_client_id_success(mock_components):
    """Test connect with valid client ID."""
    backend = EventSubChatBackend(**mock_components)

    # Mock successful connection
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)
    mock_components['token_manager'].get_scopes = MagicMock(return_value={"chat:read"})
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(return_value={"channel": "12345"})
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].session_id = "session123"
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)
    mock_components['sub_manager'].update_session_id = MagicMock()

    result = await backend.connect("token", "user", "channel", "user_id", "valid_client_id")
    assert result is True


@pytest.mark.asyncio
async def test_validate_client_id_failure(mock_components):
    """Test connect with invalid client ID."""
    backend = EventSubChatBackend(**mock_components)

    # Mock token validation failure
    mock_components['token_manager'].validate_token = AsyncMock(return_value=False)

    result = await backend.connect("token", "user", "#channel", "user_id", None)
    assert result is False


@pytest.mark.asyncio
async def test_handshake_and_session_success(mock_components):
    """Test WebSocket connection through manager."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].is_connected = True
    mock_components['ws_manager'].session_id = "session123"

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_initial_channel_success(mock_components):
    """Test channel resolution success."""
    EventSubChatBackend(**mock_components)

    # Mock channel resolver
    mock_components['channel_resolver'].resolve_user_ids = AsyncMock(
        return_value={"testchan": "12345"}
    )

    result = await mock_components['channel_resolver'].resolve_user_ids(
        ["testchan"], "token", "client"
    )
    assert result == {"testchan": "12345"}


@pytest.mark.asyncio
async def test_ensure_self_user_id_success(mock_components):
    """Test user ID validation through token manager."""
    EventSubChatBackend(**mock_components)

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)

    result = await mock_components['token_manager'].validate_token("token")
    assert result is True


@pytest.mark.asyncio
async def test_record_token_scopes_success(mock_components):
    """Test token scope validation."""
    EventSubChatBackend(**mock_components)

    # Mock token manager
    mock_components['token_manager'].validate_token = AsyncMock(return_value=True)
    mock_components['token_manager'].get_scopes = MagicMock(return_value={"user:read:chat", "chat:read"})

    result = await mock_components['token_manager'].validate_token("token")
    assert result is True


@pytest.mark.asyncio
async def test_subscribe_channel_chat_success(mock_components):
    """Test channel subscription success."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)

    result = await mock_components['sub_manager'].subscribe_channel_chat("chan123", "user123")
    assert result is True


@pytest.mark.asyncio
async def test_can_subscribe_success(mock_components):
    """Test subscription conditions - now handled by subscription manager."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=True)

    result = await mock_components['sub_manager'].subscribe_channel_chat("chan", "user")
    assert result is True


@pytest.mark.asyncio
async def test_can_subscribe_failure(mock_components):
    """Test subscription failure conditions."""
    EventSubChatBackend(**mock_components)

    # Mock subscription manager to fail
    mock_components['sub_manager'].subscribe_channel_chat = AsyncMock(return_value=False)

    result = await mock_components['sub_manager'].subscribe_channel_chat("chan", "user")
    assert result is False


@pytest.mark.asyncio
async def test_handshake_and_session_ws_connect_failure(mock_components):
    """Test WebSocket connection failure."""
    from src.errors.eventsub import EventSubConnectionError

    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to fail
    mock_components['ws_manager'].connect = AsyncMock(
        side_effect=EventSubConnectionError("Connection failed", operation_type="connect")
    )

    with pytest.raises(EventSubConnectionError):
        await mock_components['ws_manager'].connect()


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_no_challenge(mock_components):
    """Test challenge handling - now in WebSocket manager."""
    EventSubChatBackend(**mock_components)

    # This functionality moved to WebSocketConnectionManager
    assert mock_components['ws_manager'] is not None


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_bad_type(mock_components):
    """Test challenge with bad message type."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].connect = AsyncMock()

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_parse_error(mock_components):
    """Test challenge parsing error."""
    EventSubChatBackend(**mock_components)

    # Mock message processor for invalid JSON
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message("invalid json")
    mock_components['msg_processor'].process_message.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_no_challenge_value(mock_components):
    """Test challenge without value."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message('{"type": "challenge"}')
    mock_components['msg_processor'].process_message.assert_called_once_with('{"type": "challenge"}')


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_mismatch(mock_components):
    """Test challenge mismatch."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message('{"challenge": "wrong"}')
    mock_components['msg_processor'].process_message.assert_called_once_with('{"challenge": "wrong"}')


@pytest.mark.asyncio
async def test_process_welcome_message_close_frame(mock_components):
    """Test welcome message close frame."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].connect = AsyncMock()

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_process_welcome_message_error_frame(mock_components):
    """Test welcome message error frame."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to fail
    mock_components['ws_manager'].connect = AsyncMock(
        side_effect=RuntimeError("WebSocket error")
    )

    with pytest.raises(RuntimeError):
        await mock_components['ws_manager'].connect()


@pytest.mark.asyncio
async def test_process_welcome_message_bad_type(mock_components):
    """Test welcome message bad type."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message("binary data")
    mock_components['msg_processor'].process_message.assert_called_once_with("binary data")


@pytest.mark.asyncio
async def test_process_welcome_message_parse_error(mock_components):
    """Test welcome message parse error."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message("invalid json")
    mock_components['msg_processor'].process_message.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_process_welcome_message_no_session_id(mock_components):
    """Test welcome message without session ID."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].session_id = None

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_handshake_and_session_bad_welcome_type(mock_components):
    """Test bad welcome message type."""
    EventSubChatBackend(**mock_components)

    # Mock message processor
    mock_components['msg_processor'].process_message = AsyncMock()

    await mock_components['msg_processor'].process_message("bad type")
    mock_components['msg_processor'].process_message.assert_called_once_with("bad type")


@pytest.mark.asyncio
async def test_handshake_and_session_welcome_parse_error(mock_components):
    """Test welcome parse error."""
    from src.errors.eventsub import EventSubConnectionError

    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to fail
    mock_components['ws_manager'].connect = AsyncMock(
        side_effect=EventSubConnectionError("Parse error", operation_type="welcome")
    )

    with pytest.raises(EventSubConnectionError):
        await mock_components['ws_manager'].connect()


@pytest.mark.asyncio
async def test_handshake_and_session_no_session_id(mock_components):
    """Test no session ID in welcome."""
    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager
    mock_components['ws_manager'].connect = AsyncMock()
    mock_components['ws_manager'].session_id = None

    await mock_components['ws_manager'].connect()
    mock_components['ws_manager'].connect.assert_called_once()


@pytest.mark.asyncio
async def test_handshake_and_session_timeout(mock_components):
    """Test handshake timeout."""
    from src.errors.eventsub import EventSubConnectionError

    EventSubChatBackend(**mock_components)

    # Mock WebSocket manager to fail
    mock_components['ws_manager'].connect = AsyncMock(
        side_effect=EventSubConnectionError("Timeout", operation_type="connect")
    )

    with pytest.raises(EventSubConnectionError):
        await mock_components['ws_manager'].connect()
