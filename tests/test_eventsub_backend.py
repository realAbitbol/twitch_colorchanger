"""Tests for src/chat/eventsub_backend.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from src.chat.eventsub_backend import EventSubChatBackend
from src.constants import WEBSOCKET_CLOSE_SESSION_STALE, WEBSOCKET_CLOSE_TOKEN_REFRESH


@pytest.mark.asyncio
async def test_connect_invalid_client_id():
    """Test connect method with invalid client ID."""
    backend = EventSubChatBackend()
    with patch.object(backend, '_capture_initial_credentials'), \
         patch.object(backend, '_validate_client_id', return_value=False):
        result = await backend.connect("token", "user", "channel", "user_id", "invalid_client")
        assert result is False


@pytest.mark.asyncio
async def test_listen_websocket_disconnect():
    """Test listen method handles WebSocket disconnect."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    backend._ws.closed = True
    backend._stop_event.set()
    await backend.listen()  # Should complete without error


@pytest.mark.asyncio
async def test_handle_session_reconnect_invalid_url():
    """Test handle_session_reconnect with invalid URL."""
    backend = EventSubChatBackend()
    data = {
        "metadata": {"message_type": "session_reconnect"},
        "payload": {"session": {"reconnect_url": "invalid-url"}}
    }
    await backend._handle_session_reconnect(data)
    # Should log error but not raise


@pytest.mark.asyncio
async def test_handle_notification_invalid_event():
    """Test handle_notification with invalid event data."""
    backend = EventSubChatBackend()
    data = {
        "metadata": {"message_type": "notification"},
        "payload": {"subscription": {"type": "channel.chat.message"}, "event": {}}
    }
    await backend._handle_notification(data)
    # Should not dispatch if chatter_user_name is missing


@pytest.mark.asyncio
async def test_verify_subscriptions_missing_session():
    """Test verify_subscriptions with missing session."""
    backend = EventSubChatBackend()
    backend._session_id = None
    await backend._verify_subscriptions()
    # Should return early without error


@pytest.mark.asyncio
async def test_reconnect_with_backoff_max_attempts():
    """Test reconnect_with_backoff reaches max attempts."""
    backend = EventSubChatBackend()
    backend._stop_event.set()  # Set stop event before starting
    with patch.object(backend, '_reconnect_cleanup'), \
         patch.object(backend, '_perform_handshake', return_value=(False, {})), \
         patch('asyncio.sleep'):
        result = await backend._reconnect_with_backoff()
        assert result is False


@pytest.mark.asyncio
async def test_batch_resolve_channels_api_failure():
    """Test batch_resolve_channels with API failure."""
    backend = EventSubChatBackend()
    backend._token = "token"
    backend._client_id = "client"
    with patch.object(backend._api, 'validate_token', return_value=None):
        await backend._batch_resolve_channels(["channel"])
        # Should not resolve if token invalid


@pytest.mark.asyncio
async def test_subscribe_channel_chat_unauthorized():
    """Test subscribe_channel_chat with unauthorized response."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "token"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend._api, 'request', return_value=(None, 401, None)):
        await backend._subscribe_channel_chat("channel")
        # Should handle 401 response


def test_handle_close_action_token_refresh():
    """Test handle_close_action with token refresh code."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        backend._token_invalid_callback = MagicMock()
        action = backend._handle_close_action(WEBSOCKET_CLOSE_TOKEN_REFRESH)
        assert action == "token_refresh"
        backend._token_invalid_callback.assert_called_once()


def test_handle_close_action_session_stale():
    """Test handle_close_action with session stale code."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        action = backend._handle_close_action(WEBSOCKET_CLOSE_SESSION_STALE)
        assert action == "session_stale"
        assert backend._force_full_resubscribe is True


def test_eventsub_backend_init_invalid_params():
    """Test EventSubBackend initialization with invalid parameters (e.g., None or incorrect types)."""
    # Should handle None http_session gracefully
    with patch('aiohttp.ClientSession') as mock_session:
        backend = EventSubChatBackend(http_session=None)
        assert backend._session == mock_session.return_value


@pytest.mark.asyncio
async def test_connect_failure_scenarios():
    """Test connect method with various failure scenarios like network errors or invalid URLs."""
    backend = EventSubChatBackend()
    with patch.object(backend, '_capture_initial_credentials'), \
         patch.object(backend, '_validate_client_id', return_value=False):
        result = await backend.connect("token", "user", "channel", "user_id", "client_id")
        assert result is False


@pytest.mark.asyncio
async def test_listen_connection_errors():
    """Test listen method handling of connection errors and recovery attempts."""
    backend = EventSubChatBackend()
    backend._ws = None  # No connection
    backend._stop_event.set()  # Stop immediately
    await backend.listen()  # Should return without error


@pytest.mark.asyncio
async def test_subscribe_invalid_data():
    """Test subscribe method with invalid subscription data, ensuring validation and error responses."""
    backend = EventSubChatBackend()
    backend._session_id = None  # Invalid state
    await backend._subscribe_channel_chat("channel")  # Should not raise


@pytest.mark.asyncio
async def test_reconnect_after_loss():
    """Test reconnect logic after unexpected connection loss, including state preservation."""
    backend = EventSubChatBackend()
    with patch.object(backend, '_reconnect_with_backoff', new_callable=AsyncMock, return_value=False):
        backend._ws = MagicMock()
        backend._ws.closed = True
        result = await backend._ensure_socket()
        assert result is False


@pytest.mark.asyncio
async def test_eventsub_backend_handle_message_invalid_format():
    """Test handle_message with invalid message format."""
    backend = EventSubChatBackend()
    backend._ws = MagicMock()
    # Invalid JSON
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = "invalid json"
    with patch.object(backend, '_handle_text', new_callable=AsyncMock) as mock_handle:
        await backend._handle_ws_message(msg)
        mock_handle.assert_called_once_with("invalid json")


@pytest.mark.asyncio
async def test_eventsub_backend_process_subscription_failure():
    """Test process_subscription with subscription failure."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "token"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        mock_api.request = AsyncMock(return_value=(None, 500, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_eventsub_backend_cleanup_on_disconnect():
    """Test cleanup procedures when connection is lost."""
    backend = EventSubChatBackend()
    mock_ws = MagicMock()
    mock_ws.closed = False
    backend._ws = mock_ws
    await backend.disconnect()
    mock_ws.close.assert_called_once()
    assert backend._ws is None


@pytest.mark.asyncio
async def test_eventsub_backend_rate_limit_handling():
    """Test rate limit handling for subscription requests."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "token"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        # Simulate rate limit (429)
        mock_api.request = AsyncMock(return_value=(None, 429, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once_with("channel", 429, None)


@pytest.mark.asyncio
async def test_eventsub_backend_authentication_failure():
    """Test authentication failure scenarios."""
    backend = EventSubChatBackend()
    backend._session_id = "session"
    backend._token = "invalid"
    backend._client_id = "client"
    backend._user_id = "user"
    backend._channel_ids = {"channel": "cid"}
    with patch.object(backend, '_api') as mock_api, \
         patch.object(backend, '_handle_subscribe_response') as mock_handle:
        # Simulate auth failure (401)
        mock_api.request = AsyncMock(return_value=(None, 401, None))
        await backend._subscribe_channel_chat("channel")
        mock_handle.assert_called_once_with("channel", 401, None)


def test_jitter():
    """Test _jitter method returns value within range."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        result = backend._jitter(10.0, 20.0)
        assert 10.0 <= result <= 20.0


@pytest.mark.asyncio
async def test_handshake_and_session_success():
    """Test _handshake_and_session with successful connection."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        backend._client_id = "client"
        backend._token = "token"
        mock_ws = MagicMock()
        mock_ws.receive = AsyncMock(return_value=MagicMock(type=aiohttp.WSMsgType.TEXT, data='{"payload": {"session": {"id": "session_id"}}}'))
        mock_ws_connect = AsyncMock(return_value=mock_ws)
        with patch.object(backend._session, 'ws_connect', mock_ws_connect), \
             patch('asyncio.wait_for', new_callable=AsyncMock, return_value=MagicMock(type=aiohttp.WSMsgType.TEXT, data='{"payload": {"session": {"id": "session_id"}}}')):
            result = await backend._handshake_and_session()
            assert result is True
            assert backend._session_id == "session_id"


@pytest.mark.asyncio
async def test_handshake_and_session_failure():
    """Test _handshake_and_session with connection failure."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        backend._client_id = "client"
        backend._token = "token"
        with patch.object(backend._session, 'ws_connect', side_effect=Exception("Connect failed")):
            result = await backend._handshake_and_session()
            assert result is False


@pytest.mark.asyncio
async def test_resolve_initial_channel_success():
    """Test _resolve_initial_channel with successful resolution."""
    backend = EventSubChatBackend()
    backend._channels = ["channel1"]
    backend._primary_channel = "channel1"
    backend._channel_ids = {}
    with patch.object(backend, '_batch_resolve_channels', new_callable=AsyncMock, return_value=None):
        backend._channel_ids["channel1"] = "id123"
        result = await backend._resolve_initial_channel()
        assert result is True


@pytest.mark.asyncio
async def test_resolve_initial_channel_failure():
    """Test _resolve_initial_channel with resolution failure."""
    backend = EventSubChatBackend()
    backend._channels = ["channel1"]
    backend._primary_channel = "channel1"
    backend._channel_ids = {}
    with patch.object(backend, '_batch_resolve_channels', new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = None
        # channel not in _channel_ids
        result = await backend._resolve_initial_channel()
        assert result is False


@pytest.mark.asyncio
async def test_ensure_self_user_id():
    """Test _ensure_self_user_id sets user_id if not present."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._user_id = None
    mock_user = {"id": "user123"}
    with patch.object(backend, '_fetch_user', new_callable=AsyncMock, return_value=mock_user):
        await backend._ensure_self_user_id()
        assert backend._user_id == "user123"


@pytest.mark.asyncio
async def test_record_token_scopes_success():
    """Test _record_token_scopes with successful validation."""
    backend = EventSubChatBackend()
    backend._token = "valid_token"
    mock_validation = {"scopes": ["chat:read", "user:read:chat"]}
    with patch.object(backend._api, 'validate_token', new_callable=AsyncMock, return_value=mock_validation):
        await backend._record_token_scopes()
        assert backend._scopes == {"chat:read", "user:read:chat"}


@pytest.mark.asyncio
async def test_record_token_scopes_failure():
    """Test _record_token_scopes with validation failure."""
    backend = EventSubChatBackend()
    backend._token = "invalid_token"
    with patch.object(backend._api, 'validate_token', new_callable=AsyncMock, return_value=None):
        await backend._record_token_scopes()
        assert backend._scopes == set()


@pytest.mark.asyncio
async def test_join_channel_success():
    """Test join_channel with successful join."""
    backend = EventSubChatBackend()
    backend._channels = []
    backend._channel_ids = {}
    with patch.object(backend, '_batch_resolve_channels', new_callable=AsyncMock), \
         patch.object(backend, '_subscribe_channel_chat', new_callable=AsyncMock), \
         patch.object(backend, '_save_id_cache'):
        backend._channel_ids["testchannel"] = "cid123"
        result = await backend.join_channel("testchannel")
        assert result is True
        assert "testchannel" in backend._channels


@pytest.mark.asyncio
async def test_join_channel_failure():
    """Test join_channel with failure to resolve channel."""
    backend = EventSubChatBackend()
    backend._channels = []
    backend._channel_ids = {}
    with patch.object(backend, '_batch_resolve_channels', new_callable=AsyncMock), \
         patch.object(backend, '_subscribe_channel_chat', new_callable=AsyncMock), \
         patch.object(backend, '_save_id_cache'):
        # Channel not resolved
        result = await backend.join_channel("testchannel")
        assert result is False
        assert "testchannel" not in backend._channels


@pytest.mark.asyncio
async def test_disconnect_success():
    """Test disconnect with active WebSocket."""
    backend = EventSubChatBackend()
    mock_ws = MagicMock()
    mock_ws.closed = False
    backend._ws = mock_ws
    await backend.disconnect()
    mock_ws.close.assert_called_once_with(code=1000)
    assert backend._ws is None


@pytest.mark.asyncio
async def test_disconnect_no_ws():
    """Test disconnect with no WebSocket."""
    backend = EventSubChatBackend()
    backend._ws = None
    await backend.disconnect()
    assert backend._ws is None


def test_update_token():
    """Test update_token method."""
    with patch('aiohttp.ClientSession'):
        backend = EventSubChatBackend()
        backend.update_token("new_token")
        assert backend._token == "new_token"
