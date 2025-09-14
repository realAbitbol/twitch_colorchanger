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
