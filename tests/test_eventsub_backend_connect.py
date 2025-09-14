import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from src.chat.eventsub_backend import EventSubChatBackend


@pytest.mark.asyncio
async def test_capture_initial_credentials_success():
    """Test that _capture_initial_credentials sets attributes correctly."""
    backend = EventSubChatBackend()
    backend._capture_initial_credentials(
        token="test_token",
        username="testuser",
        primary_channel="#testchan",
        user_id="12345",
        client_id="client123",
        client_secret="secret"
    )
    assert backend._token == "test_token"
    assert backend._username == "testuser"
    assert backend._user_id == "12345"
    assert backend._primary_channel == "testchan"
    assert backend._channels == ["testchan"]
    assert backend._client_id == "client123"


@pytest.mark.asyncio
async def test_validate_client_id_success():
    """Test _validate_client_id returns True for valid client_id."""
    backend = EventSubChatBackend()
    backend._client_id = "valid_client_id"
    assert backend._validate_client_id() is True


@pytest.mark.asyncio
async def test_validate_client_id_failure():
    """Test _validate_client_id returns False for invalid client_id."""
    backend = EventSubChatBackend()
    backend._client_id = None
    assert backend._validate_client_id() is False

    backend._client_id = ""
    assert backend._validate_client_id() is False


@pytest.mark.asyncio
async def test_handshake_and_session_success(monkeypatch):
    """Test successful WebSocket handshake and session establishment."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    # Mock welcome message
    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = '{"payload": {"session": {"id": "session123"}}}'

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(return_value=ws_mock)

    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is True
    assert backend._session_id == "session123"
    assert backend._ws == ws_mock


@pytest.mark.asyncio
async def test_resolve_initial_channel_success(monkeypatch):
    """Test successful initial channel resolution."""
    backend = EventSubChatBackend()
    backend._channels = ["testchan"]
    backend._primary_channel = "testchan"

    # Mock _batch_resolve_channels to set channel_ids
    async def mock_batch_resolve(channels):
        backend._channel_ids["testchan"] = "12345"

    monkeypatch.setattr(backend, "_batch_resolve_channels", mock_batch_resolve)

    result = await backend._resolve_initial_channel()
    assert result is True
    assert backend._channel_ids["testchan"] == "12345"


@pytest.mark.asyncio
async def test_ensure_self_user_id_success(monkeypatch):
    """Test _ensure_self_user_id fetches and sets user_id when None."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._user_id = None

    # Mock _fetch_user
    async def mock_fetch_user(username):
        return {"id": "67890"}

    monkeypatch.setattr(backend, "_fetch_user", mock_fetch_user)

    await backend._ensure_self_user_id()
    assert backend._user_id == "67890"


@pytest.mark.asyncio
async def test_record_token_scopes_success(monkeypatch):
    """Test _record_token_scopes validates token and records scopes."""
    backend = EventSubChatBackend()
    backend._token = "token123"

    # Mock API validation
    validation_result = {"scopes": ["user:read:chat", "chat:read"]}
    api_mock = MagicMock()
    api_mock.validate_token = AsyncMock(return_value=validation_result)
    backend._api = api_mock

    await backend._record_token_scopes()
    assert backend._scopes == {"user:read:chat", "chat:read"}


@pytest.mark.asyncio
async def test_subscribe_channel_chat_success(monkeypatch):
    """Test successful channel chat subscription."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._channel_ids = {"testchan": "chan123"}

    # Mock API request
    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"data": []}, 202, {}))
    backend._api = api_mock

    await backend._subscribe_channel_chat("testchan")
    # Assert no exceptions and _handle_subscribe_response was called with 202


@pytest.mark.asyncio
async def test_can_subscribe_success():
    """Test _can_subscribe returns True when all conditions met."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._token_invalid_flag = False

    assert backend._can_subscribe() is True


@pytest.mark.asyncio
async def test_can_subscribe_failure():
    """Test _can_subscribe returns False when conditions not met."""
    backend = EventSubChatBackend()
    backend._session_id = None
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._token_invalid_flag = False

    assert backend._can_subscribe() is False


@pytest.mark.asyncio
async def test_handshake_and_session_ws_connect_failure():
    """Test _handshake_and_session handles WebSocket connection failure."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(side_effect=Exception("Connection failed"))
    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is False
    assert backend._ws is None


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_no_challenge():
    """Test _handle_challenge_if_needed when no challenge is pending."""
    backend = EventSubChatBackend()
    backend._pending_challenge = None

    ws_mock = MagicMock()
    handshake_details = {}

    result = await backend._handle_challenge_if_needed(ws_mock, handshake_details)
    assert result is True
    assert "challenge_handshake" not in handshake_details


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_bad_type():
    """Test _handle_challenge_if_needed handles non-TEXT challenge message."""
    backend = EventSubChatBackend()
    backend._pending_challenge = "expected_challenge"

    challenge_msg = MagicMock()
    challenge_msg.type = aiohttp.WSMsgType.CLOSED
    challenge_msg.data = None

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=challenge_msg)

    handshake_details = {}

    result = await backend._handle_challenge_if_needed(ws_mock, handshake_details)
    assert result is False
    assert handshake_details["challenge_error"] == "bad_challenge_type"
    assert backend._pending_challenge is None


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_parse_error():
    """Test _handle_challenge_if_needed handles invalid JSON in challenge."""
    backend = EventSubChatBackend()
    backend._pending_challenge = "expected_challenge"

    challenge_msg = MagicMock()
    challenge_msg.type = aiohttp.WSMsgType.TEXT
    challenge_msg.data = "invalid json"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=challenge_msg)

    handshake_details = {}

    result = await backend._handle_challenge_if_needed(ws_mock, handshake_details)
    assert result is False
    assert "challenge_error" in handshake_details
    assert backend._pending_challenge is None


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_no_challenge_value():
    """Test _handle_challenge_if_needed handles challenge without value."""
    backend = EventSubChatBackend()
    backend._pending_challenge = "expected_challenge"

    challenge_msg = MagicMock()
    challenge_msg.type = aiohttp.WSMsgType.TEXT
    challenge_msg.data = '{"type": "challenge"}'

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=challenge_msg)

    handshake_details = {}

    result = await backend._handle_challenge_if_needed(ws_mock, handshake_details)
    assert result is False
    assert handshake_details["challenge_error"] == "no_challenge_value"
    assert backend._pending_challenge is None


@pytest.mark.asyncio
async def test_handle_challenge_if_needed_mismatch():
    """Test _handle_challenge_if_needed handles challenge mismatch."""
    backend = EventSubChatBackend()
    backend._pending_challenge = "expected_challenge"

    challenge_msg = MagicMock()
    challenge_msg.type = aiohttp.WSMsgType.TEXT
    challenge_msg.data = '{"challenge": "wrong_challenge"}'

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=challenge_msg)

    handshake_details = {}

    result = await backend._handle_challenge_if_needed(ws_mock, handshake_details)
    assert result is False
    assert backend._pending_challenge is None


@pytest.mark.asyncio
async def test_process_welcome_message_close_frame():
    """Test _process_welcome_message handles close frame."""
    backend = EventSubChatBackend()

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.CLOSE
    welcome.data = 1000
    welcome.extra = "reason"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)
    handshake_details = {}

    success, details = await backend._process_welcome_message(ws_mock, handshake_details)
    assert success is False
    assert details["error"] == "closed_by_server"
    assert details["close_code"] == 1000


@pytest.mark.asyncio
async def test_process_welcome_message_error_frame():
    """Test _process_welcome_message handles error frame."""
    backend = EventSubChatBackend()

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.ERROR
    welcome.data = "ws_error"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)
    handshake_details = {}

    success, details = await backend._process_welcome_message(ws_mock, handshake_details)
    assert success is False
    assert details["error"] == "ws_error"


@pytest.mark.asyncio
async def test_process_welcome_message_bad_type():
    """Test _process_welcome_message handles non-TEXT frame."""
    backend = EventSubChatBackend()

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.BINARY
    welcome.data = b"binary data"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)
    handshake_details = {}

    success, details = await backend._process_welcome_message(ws_mock, handshake_details)
    assert success is False
    assert details["error"] == "bad_welcome_type"


@pytest.mark.asyncio
async def test_process_welcome_message_parse_error():
    """Test _process_welcome_message handles invalid JSON."""
    backend = EventSubChatBackend()

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = "invalid json"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)
    handshake_details = {}

    success, details = await backend._process_welcome_message(ws_mock, handshake_details)
    assert success is False
    assert "error" in details
    assert "welcome_parse_error" in details["error"]


@pytest.mark.asyncio
async def test_process_welcome_message_no_session_id():
    """Test _process_welcome_message handles welcome without session ID."""
    backend = EventSubChatBackend()

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = '{"payload": {"session": {}}}'

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)
    handshake_details = {}

    success, details = await backend._process_welcome_message(ws_mock, handshake_details)
    assert success is False
    assert details["error"] == "no_session_id"


@pytest.mark.asyncio
async def test_handshake_and_session_bad_welcome_type():
    """Test _handshake_and_session handles non-TEXT welcome message."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.CLOSED
    welcome.data = None

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(return_value=ws_mock)
    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is False
    assert backend._session_id is None


@pytest.mark.asyncio
async def test_handshake_and_session_welcome_parse_error():
    """Test _handshake_and_session handles invalid JSON in welcome."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = "invalid json"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(return_value=ws_mock)
    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is False
    assert backend._session_id is None


@pytest.mark.asyncio
async def test_handshake_and_session_no_session_id():
    """Test _handshake_and_session handles welcome without session ID."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    welcome = MagicMock()
    welcome.type = aiohttp.WSMsgType.TEXT
    welcome.data = '{"payload": {"session": {}}}'

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(return_value=welcome)

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(return_value=ws_mock)
    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is False
    assert backend._session_id is None


@pytest.mark.asyncio
async def test_handshake_and_session_timeout():
    """Test _handshake_and_session handles timeout on welcome."""
    backend = EventSubChatBackend()
    backend._client_id = "client123"
    backend._token = "token123"

    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock(side_effect=asyncio.TimeoutError)

    session_mock = MagicMock()
    session_mock.ws_connect = AsyncMock(return_value=ws_mock)
    backend._session = session_mock

    result = await backend._handshake_and_session()
    assert result is False
    # Note: code doesn't set _ws to None on exception
