from unittest.mock import AsyncMock, MagicMock

import pytest

from src.chat.eventsub_backend import EventSubChatBackend


@pytest.mark.asyncio
async def test_subscribe_channel_chat_success():
    """Test successful channel chat subscription."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._channel_ids = {"testchan": "chan123"}

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"data": []}, 202, {}))
    backend._api = api_mock

    await backend._subscribe_channel_chat("testchan")
    api_mock.request.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_channel_chat_401():
    """Test subscription with 401 unauthorized."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "invalid_token"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._channel_ids = {"testchan": "chan123"}
    backend._consecutive_subscribe_401 = 0

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"error": "Unauthorized"}, 401, {}))
    backend._api = api_mock

    await backend._subscribe_channel_chat("testchan")
    assert backend._consecutive_subscribe_401 == 1


@pytest.mark.asyncio
async def test_subscribe_channel_chat_429():
    """Test subscription with 429 rate limit."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._channel_ids = {"testchan": "chan123"}

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"error": "Too Many Requests"}, 429, {}))
    backend._api = api_mock

    await backend._subscribe_channel_chat("testchan")
    api_mock.request.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_channel_chat_missing_scopes():
    """Test subscription with 403 missing scopes."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"
    backend._token = "token123"
    backend._client_id = "client123"
    backend._user_id = "user123"
    backend._channel_ids = {"testchan": "chan123"}
    backend._scopes = set()  # No scopes

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"error": "Forbidden"}, 403, {}))
    backend._api = api_mock

    await backend._subscribe_channel_chat("testchan")
    api_mock.request.assert_called_once()


@pytest.mark.asyncio
async def test_handle_subscribe_response_202():
    """Test handling 202 accepted response."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._consecutive_subscribe_401 = 1

    backend._handle_subscribe_response("testchan", 202, {})
    assert backend._consecutive_subscribe_401 == 0


@pytest.mark.asyncio
async def test_handle_subscribe_response_401():
    """Test handling 401 unauthorized response."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._consecutive_subscribe_401 = 0
    backend._token_invalid_flag = False

    backend._handle_subscribe_response("testchan", 401, {"error": "Unauthorized"})
    assert backend._consecutive_subscribe_401 == 1
    assert backend._token_invalid_flag is False  # Not yet 2


@pytest.mark.asyncio
async def test_verify_subscriptions_success():
    """Test successful subscription verification."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"
    backend._session_id = "session123"
    backend._channels = ["testchan"]
    backend._channel_ids = {"testchan": "chan123"}

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"data": [{"type": "channel.chat.message", "transport": {"session_id": "session123"}, "condition": {"broadcaster_user_id": "chan123"}}]}, 200, {}))
    backend._api = api_mock

    await backend._verify_subscriptions()
    api_mock.request.assert_called_once()


@pytest.mark.asyncio
async def test_verify_subscriptions_missing():
    """Test verification with missing subscriptions."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"
    backend._session_id = "session123"
    backend._channels = ["testchan"]
    backend._channel_ids = {"testchan": "chan123"}

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"data": []}, 200, {}))  # No active subs
    backend._api = api_mock

    backend._resubscribe_missing = AsyncMock()
    await backend._verify_subscriptions()
    backend._resubscribe_missing.assert_called_once_with({"chan123"})


@pytest.mark.asyncio
async def test_resubscribe_missing_success():
    """Test successful resubscription of missing channels."""
    backend = EventSubChatBackend()
    backend._channel_ids = {"testchan": "chan123"}
    backend._channels = ["testchan"]

    backend._subscribe_channel_chat = AsyncMock()
    await backend._resubscribe_missing({"chan123"})
    backend._subscribe_channel_chat.assert_called_once_with("testchan")


@pytest.mark.asyncio
async def test_resubscribe_missing_failure():
    """Test resubscription when channel not in ids."""
    backend = EventSubChatBackend()
    backend._channel_ids = {}
    backend._channels = []

    backend._subscribe_channel_chat = AsyncMock()
    await backend._resubscribe_missing({"chan123"})
    backend._subscribe_channel_chat.assert_not_called()
