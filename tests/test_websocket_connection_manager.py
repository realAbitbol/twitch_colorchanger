"""Unit tests for WebSocketConnectionManager."""

import json
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from src.chat.websocket_connection_manager import WebSocketConnectionManager
from src.errors.eventsub import EventSubConnectionError


class TestWebSocketConnectionManager:
    """Test suite for WebSocketConnectionManager."""

    @pytest.fixture
    def mock_session(self):
        """Mock aiohttp.ClientSession."""
        session = Mock(spec=aiohttp.ClientSession)
        return session

    @pytest.fixture
    def mock_ws(self):
        """Mock aiohttp.ClientWebSocketResponse."""
        ws = Mock(spec=aiohttp.ClientWebSocketResponse)
        ws.closed = False
        ws.send_json = AsyncMock()
        ws.receive = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.fixture
    def manager(self, mock_session):
        """Create WebSocketConnectionManager instance."""
        return WebSocketConnectionManager(
            session=mock_session,
            token="test_token",
            client_id="test_client_id"
        )

    async def test_init(self, mock_session):
        """Test initialization."""
        manager = WebSocketConnectionManager(
            session=mock_session,
            token="test_token",
            client_id="test_client_id",
            ws_url="wss://custom.url"
        )

        assert manager.session == mock_session
        assert manager.token == "test_token"
        assert manager.client_id == "test_client_id"
        assert manager.ws_url == "wss://custom.url"
        assert manager.ws is None
        assert manager.session_id is None
        assert manager.pending_reconnect_session_id is None
        assert manager.pending_challenge is None
        assert manager.backoff == 1.0
        assert manager.max_backoff == 60.0  # EVENTSUB_MAX_BACKOFF_SECONDS
        assert isinstance(manager.last_activity, float)
        assert not manager._stop_event.is_set()
        assert not manager._reconnect_requested

    async def test_init_default_url(self, mock_session):
        """Test initialization with default URL."""
        manager = WebSocketConnectionManager(
            session=mock_session,
            token="test_token",
            client_id="test_client_id"
        )

        assert manager.ws_url == "wss://eventsub.wss.twitch.tv/ws"

    async def test_is_connected_none_ws(self, manager):
        """Test is_connected when ws is None."""
        assert not manager.is_connected

    async def test_is_connected_closed_ws(self, manager, mock_ws):
        """Test is_connected when ws is closed."""
        manager.ws = mock_ws
        mock_ws.closed = True
        assert not manager.is_connected

    async def test_is_connected_open_ws(self, manager, mock_ws):
        """Test is_connected when ws is open."""
        manager.ws = mock_ws
        mock_ws.closed = False
        assert manager.is_connected

    async def test_connect_success(self, manager, mock_session, mock_ws, monkeypatch):
        """Test successful connection."""
        # Mock ws_connect
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        # Mock welcome message
        welcome_msg = Mock()
        welcome_msg.type = aiohttp.WSMsgType.TEXT
        welcome_msg.data = json.dumps({
            "payload": {
                "session": {"id": "test_session_id"}
            }
        })
        mock_ws.receive = AsyncMock(return_value=welcome_msg)

        # Mock time.monotonic
        monkeypatch.setattr('time.monotonic', lambda: 123.45)

        await manager.connect()

        assert manager.ws == mock_ws
        assert manager.session_id == "test_session_id"
        assert isinstance(manager.last_activity, float)
        mock_session.ws_connect.assert_called_once_with(
            "wss://eventsub.wss.twitch.tv/ws",
            heartbeat=30,  # WEBSOCKET_HEARTBEAT_SECONDS
            headers={
                "Client-Id": "test_client_id",
                "Authorization": "Bearer test_token",
            },
            protocols=("twitch-eventsub-ws",),
        )

    async def test_connect_with_challenge(self, manager, mock_session, mock_ws, monkeypatch):
        """Test connection with pending challenge."""
        manager.pending_challenge = "test_challenge"

        # Mock ws_connect
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        # Mock challenge message
        challenge_msg = Mock()
        challenge_msg.type = aiohttp.WSMsgType.TEXT
        challenge_msg.data = json.dumps({"challenge": "test_challenge"})

        # Mock welcome message
        welcome_msg = Mock()
        welcome_msg.type = aiohttp.WSMsgType.TEXT
        welcome_msg.data = json.dumps({
            "payload": {
                "session": {"id": "test_session_id"}
            }
        })

        mock_ws.receive = AsyncMock(side_effect=[challenge_msg, welcome_msg])

        await manager.connect()

        assert manager.pending_challenge is None
        mock_ws.send_json.assert_called_with({
            "type": "challenge_response",
            "challenge": "test_challenge"
        })

    async def test_connect_failure(self, manager, mock_session):
        """Test connection failure."""
        mock_session.ws_connect = AsyncMock(side_effect=Exception("Connection failed"))

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.connect()

        assert "WebSocket connection failed" in str(exc_info.value)
        assert exc_info.value.operation_type == "connect"

    async def test_connect_welcome_invalid_type(self, manager, mock_session, mock_ws):
        """Test connection with invalid welcome message type."""
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        invalid_msg = Mock()
        invalid_msg.type = aiohttp.WSMsgType.ERROR
        mock_ws.receive = AsyncMock(return_value=invalid_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.connect()

        assert "Invalid welcome message type" in str(exc_info.value)
        assert exc_info.value.operation_type == "welcome"

    async def test_connect_no_session_id(self, manager, mock_session, mock_ws):
        """Test connection with no session ID in welcome."""
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        welcome_msg = Mock()
        welcome_msg.type = aiohttp.WSMsgType.TEXT
        welcome_msg.data = json.dumps({"payload": {}})
        mock_ws.receive = AsyncMock(return_value=welcome_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.connect()

        assert "No session ID in welcome" in str(exc_info.value)
        assert exc_info.value.operation_type == "welcome"

    async def test_disconnect_connected(self, manager, mock_ws):
        """Test disconnect when connected."""
        manager.ws = mock_ws
        manager.session_id = "test_session_id"

        await manager.disconnect()

        assert manager.ws is None
        assert manager.session_id is None
        mock_ws.close.assert_called_once_with(code=1000)

    async def test_disconnect_not_connected(self, manager):
        """Test disconnect when not connected."""
        await manager.disconnect()

        assert manager.ws is None
        assert manager.session_id is None

    async def test_disconnect_close_error(self, manager, mock_ws):
        """Test disconnect with close error."""
        manager.ws = mock_ws
        mock_ws.close = AsyncMock(side_effect=Exception("Close failed"))

        await manager.disconnect()

        # Should not raise, just log warning
        assert manager.ws is None

    async def test_send_json_connected(self, manager, mock_ws, monkeypatch):
        """Test send_json when connected."""
        manager.ws = mock_ws
        monkeypatch.setattr('src.chat.websocket_connection_manager.time.monotonic', lambda: 123.45)

        data = {"type": "test", "data": "value"}
        await manager.send_json(data)

        mock_ws.send_json.assert_called_once_with(data)
        assert isinstance(manager.last_activity, float)

    async def test_send_json_not_connected(self, manager):
        """Test send_json when not connected."""
        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.send_json({"test": "data"})

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "send"

    async def test_send_json_send_failure(self, manager, mock_ws):
        """Test send_json with send failure."""
        manager.ws = mock_ws
        mock_ws.send_json = AsyncMock(side_effect=Exception("Send failed"))

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.send_json({"test": "data"})

        assert "WebSocket send failed" in str(exc_info.value)
        assert exc_info.value.operation_type == "send"

    async def test_receive_message_connected(self, manager, mock_ws, monkeypatch):
        """Test receive_message when connected."""
        manager.ws = mock_ws
        monkeypatch.setattr('time.monotonic', lambda: 123.45)

        msg = Mock()
        mock_ws.receive = AsyncMock(return_value=msg)

        result = await manager.receive_message()

        assert result == msg
        assert isinstance(manager.last_activity, float)

    async def test_receive_message_not_connected(self, manager):
        """Test receive_message when not connected."""
        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.receive_message()

        assert "WebSocket not connected" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    async def test_receive_message_timeout(self, manager, mock_ws):
        """Test receive_message with timeout."""
        manager.ws = mock_ws
        mock_ws.receive = AsyncMock(side_effect=TimeoutError())

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.receive_message()

        assert "WebSocket receive timeout" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    async def test_receive_message_failure(self, manager, mock_ws):
        """Test receive_message with receive failure."""
        manager.ws = mock_ws
        mock_ws.receive = AsyncMock(side_effect=Exception("Receive failed"))

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.receive_message()

        assert "WebSocket receive failed" in str(exc_info.value)
        assert exc_info.value.operation_type == "receive"

    async def test_reconnect(self, manager, monkeypatch):
        """Test reconnect method."""
        mock_reconnect = AsyncMock()
        monkeypatch.setattr(manager, '_reconnect_with_backoff', mock_reconnect)

        await manager.reconnect()

        assert manager._reconnect_requested
        mock_reconnect.assert_called_once()

    async def test_handle_challenge_no_ws(self, manager):
        """Test _handle_challenge with no ws."""
        manager.pending_challenge = "test"
        await manager._handle_challenge()
        # Should return without doing anything

    async def test_handle_challenge_no_pending(self, manager, mock_ws):
        """Test _handle_challenge with no pending challenge."""
        manager.ws = mock_ws
        await manager._handle_challenge()
        # Should return without doing anything

    async def test_handle_challenge_success(self, manager, mock_ws):
        """Test successful challenge handling."""
        manager.ws = mock_ws
        manager.pending_challenge = "test_challenge"

        challenge_msg = Mock()
        challenge_msg.type = aiohttp.WSMsgType.TEXT
        challenge_msg.data = json.dumps({"challenge": "test_challenge"})

        mock_ws.receive = AsyncMock(return_value=challenge_msg)

        await manager._handle_challenge()

        assert manager.pending_challenge is None
        mock_ws.send_json.assert_called_with({
            "type": "challenge_response",
            "challenge": "test_challenge"
        })

    async def test_handle_challenge_invalid_type(self, manager, mock_ws):
        """Test challenge handling with invalid message type."""
        manager.ws = mock_ws
        manager.pending_challenge = "test_challenge"

        invalid_msg = Mock()
        invalid_msg.type = aiohttp.WSMsgType.ERROR
        mock_ws.receive = AsyncMock(return_value=invalid_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager._handle_challenge()

        assert "Invalid challenge message type" in str(exc_info.value)
        assert exc_info.value.operation_type == "challenge"

    async def test_handle_challenge_mismatch(self, manager, mock_ws):
        """Test challenge handling with challenge mismatch."""
        manager.ws = mock_ws
        manager.pending_challenge = "expected_challenge"

        challenge_msg = Mock()
        challenge_msg.type = aiohttp.WSMsgType.TEXT
        challenge_msg.data = json.dumps({"challenge": "wrong_challenge"})

        mock_ws.receive = AsyncMock(return_value=challenge_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager._handle_challenge()

        assert "Challenge mismatch" in str(exc_info.value)
        assert exc_info.value.operation_type == "challenge"

    async def test_process_welcome_success(self, manager, mock_ws):
        """Test successful welcome processing."""
        manager.ws = mock_ws

        welcome_msg = Mock()
        welcome_msg.type = aiohttp.WSMsgType.TEXT
        welcome_msg.data = json.dumps({
            "payload": {
                "session": {"id": "test_session_id"}
            }
        })

        mock_ws.receive = AsyncMock(return_value=welcome_msg)

        await manager._process_welcome()

        assert manager.session_id == "test_session_id"

    async def test_process_welcome_no_ws(self, manager):
        """Test welcome processing with no ws."""
        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager._process_welcome()

        assert "No WebSocket connection" in str(exc_info.value)
        assert exc_info.value.operation_type == "welcome"

    async def test_process_welcome_invalid_type(self, manager, mock_ws):
        """Test welcome processing with invalid message type."""
        manager.ws = mock_ws

        invalid_msg = Mock()
        invalid_msg.type = aiohttp.WSMsgType.ERROR
        mock_ws.receive = AsyncMock(return_value=invalid_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager._process_welcome()

        assert "Invalid welcome message type" in str(exc_info.value)
        assert exc_info.value.operation_type == "welcome"

    async def test_process_welcome_no_session_id(self, manager, mock_ws):
        """Test welcome processing with no session ID."""
        manager.ws = mock_ws

        welcome_msg = Mock()
        welcome_msg.type = aiohttp.WSMsgType.TEXT
        welcome_msg.data = json.dumps({"payload": {}})
        mock_ws.receive = AsyncMock(return_value=welcome_msg)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager._process_welcome()

        assert "No session ID in welcome" in str(exc_info.value)
        assert exc_info.value.operation_type == "welcome"

    async def test_jitter(self, manager, monkeypatch):
        """Test _jitter method."""
        monkeypatch.setattr('secrets.randbelow', lambda x: 500)  # 0.5 * 1000

        result = manager._jitter(1.0, 3.0)
        assert 1.5 <= result <= 3.0

    async def test_jitter_b_le_a(self, manager):
        """Test _jitter when b <= a."""
        result = manager._jitter(2.0, 2.0)
        assert result == 2.0

    async def test_reconnect_with_backoff_success(self, manager, monkeypatch):
        """Test successful reconnect with backoff."""
        mock_disconnect = AsyncMock()
        mock_connect = AsyncMock()
        mock_sleep = AsyncMock()
        monkeypatch.setattr(manager, 'disconnect', mock_disconnect)
        monkeypatch.setattr(manager, 'connect', mock_connect)
        monkeypatch.setattr('asyncio.sleep', mock_sleep)

        await manager._reconnect_with_backoff()

        mock_disconnect.assert_called_once()
        mock_sleep.assert_called_once()
        mock_connect.assert_called_once()
        assert manager.backoff == 1.0
        assert not manager._reconnect_requested

    async def test_reconnect_with_backoff_failure_then_success(self, manager, monkeypatch):
        """Test reconnect with backoff failure then success."""
        mock_disconnect = AsyncMock()
        mock_connect = AsyncMock()
        mock_sleep = AsyncMock()
        monkeypatch.setattr(manager, 'disconnect', mock_disconnect)
        monkeypatch.setattr(manager, 'connect', mock_connect)
        monkeypatch.setattr('asyncio.sleep', mock_sleep)
        monkeypatch.setattr('secrets.randbelow', lambda x: 0)

        # First connect fails, second succeeds
        mock_connect.side_effect = [Exception("Failed"), None]

        await manager._reconnect_with_backoff()

        assert mock_disconnect.call_count == 2
        assert mock_sleep.call_count == 3  # reconnect_delay, backoff, reconnect_delay
        assert mock_connect.call_count == 2
        assert manager.backoff == 1.0  # Reset on success
        assert not manager._reconnect_requested

    async def test_reconnect_with_backoff_stop_event(self, manager, monkeypatch):
        """Test reconnect with backoff stopped by stop event."""
        manager._stop_event.set()
        mock_disconnect = AsyncMock()
        monkeypatch.setattr(manager, 'disconnect', mock_disconnect)

        await manager._reconnect_with_backoff()

        mock_disconnect.assert_not_called()

    async def test_async_context_manager(self, manager, monkeypatch):
        """Test async context manager."""
        mock_connect = AsyncMock()
        mock_disconnect = AsyncMock()
        monkeypatch.setattr(manager, 'connect', mock_connect)
        monkeypatch.setattr(manager, 'disconnect', mock_disconnect)

        async with manager as mgr:
            assert mgr == manager
            mock_connect.assert_called_once()

        mock_disconnect.assert_called_once()

    async def test_connect_preserves_existing_eventsub_error(self, manager, mock_session):
        """Test that existing EventSubConnectionError is preserved."""
        original_error = EventSubConnectionError("Original error", operation_type="test")
        mock_session.ws_connect = AsyncMock(side_effect=original_error)

        with pytest.raises(EventSubConnectionError) as exc_info:
            await manager.connect()

        assert exc_info.value == original_error
        assert exc_info.value == original_error
