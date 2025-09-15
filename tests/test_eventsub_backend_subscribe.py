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


@pytest.mark.asyncio
async def test_handle_subscribe_unauthorized_consecutive():
    """Test _handle_subscribe_unauthorized increments counter."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._consecutive_subscribe_401 = 0
    backend._token_invalid_flag = False

    backend._handle_subscribe_unauthorized("testchan")
    assert backend._consecutive_subscribe_401 == 1
    assert backend._token_invalid_flag is False


@pytest.mark.asyncio
async def test_handle_subscribe_unauthorized_trigger_invalid():
    """Test _handle_subscribe_unauthorized triggers token invalid on 2nd 401."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._consecutive_subscribe_401 = 1
    backend._token_invalid_flag = False
    backend._token_invalid_callback = None

    backend._handle_subscribe_unauthorized("testchan")
    assert backend._consecutive_subscribe_401 == 2
    assert backend._token_invalid_flag is True


@pytest.mark.asyncio
async def test_handle_subscribe_unauthorized_with_callback():
    """Test _handle_subscribe_unauthorized calls callback when token invalid."""
    backend = EventSubChatBackend()
    backend._username = "testuser"
    backend._consecutive_subscribe_401 = 1
    backend._token_invalid_flag = False

    callback_mock = AsyncMock()
    backend._token_invalid_callback = callback_mock

    backend._handle_subscribe_unauthorized("testchan")
    assert callback_mock.called


@pytest.mark.asyncio
async def test_handle_list_unauthorized():
    """Test _handle_list_unauthorized logs warning."""
    backend = EventSubChatBackend()

    backend._handle_list_unauthorized({"error": "Unauthorized"})
    # No specific assertions, just ensure no exceptions


@pytest.mark.asyncio
async def test_handle_close_action_token_refresh():
    """Test _handle_close_action handles token refresh close codes."""
    backend = EventSubChatBackend()
    backend._token_invalid_flag = False

    callback_mock = AsyncMock()
    backend._token_invalid_callback = callback_mock

    action = backend._handle_close_action(4001)
    assert action == "token_refresh"
    assert backend._token_invalid_flag is True
    assert callback_mock.called


@pytest.mark.asyncio
async def test_handle_close_action_session_stale():
    """Test _handle_close_action handles session stale close code."""
    backend = EventSubChatBackend()
    backend._force_full_resubscribe = False

    action = backend._handle_close_action(4007)
    assert action == "session_stale"
    assert backend._force_full_resubscribe is True


@pytest.mark.asyncio
async def test_handle_close_action_unknown_code():
    """Test _handle_close_action handles unknown close code."""
    backend = EventSubChatBackend()

    action = backend._handle_close_action(9999)
    assert action is None


@pytest.mark.asyncio
async def test_handle_close_action_none_code():
    """Test _handle_close_action handles None close code."""
    backend = EventSubChatBackend()

    action = backend._handle_close_action(None)
    assert action is None


@pytest.mark.asyncio
async def test_verify_subscriptions_no_token():
    """Test _verify_subscriptions skips when no token."""
    backend = EventSubChatBackend()
    backend._token = None
    backend._client_id = "client123"
    backend._session_id = "session123"

    await backend._verify_subscriptions()
    # No assertions needed, just ensure no exceptions


@pytest.mark.asyncio
async def test_verify_subscriptions_no_client_id():
    """Test _verify_subscriptions skips when no client_id."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = None
    backend._session_id = "session123"

    await backend._verify_subscriptions()
    # No assertions needed


@pytest.mark.asyncio
async def test_verify_subscriptions_no_session_id():
    """Test _verify_subscriptions skips when no session_id."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"
    backend._session_id = None

    await backend._verify_subscriptions()
    # No assertions needed


@pytest.mark.asyncio
async def test_fetch_active_broadcaster_ids_401():
    """Test _fetch_active_broadcaster_ids handles 401."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"error": "Unauthorized"}, 401, {}))
    backend._api = api_mock

    result = await backend._fetch_active_broadcaster_ids()
    assert result is None


@pytest.mark.asyncio
async def test_fetch_active_broadcaster_ids_invalid_data():
    """Test _fetch_active_broadcaster_ids handles invalid response data."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=("not a dict", 200, {}))
    backend._api = api_mock

    result = await backend._fetch_active_broadcaster_ids()
    assert result is None


@pytest.mark.asyncio
async def test_fetch_active_broadcaster_ids_no_data():
    """Test _fetch_active_broadcaster_ids handles response without data."""
    backend = EventSubChatBackend()
    backend._token = "token123"
    backend._client_id = "client123"

    api_mock = MagicMock()
    api_mock.request = AsyncMock(return_value=({"no_data": []}, 200, {}))
    backend._api = api_mock

    result = await backend._fetch_active_broadcaster_ids()
    assert result == set()


@pytest.mark.asyncio
async def test_extract_broadcaster_ids_from_data_no_data():
    """Test _extract_broadcaster_ids_from_data handles no data."""
    backend = EventSubChatBackend()

    result = backend._extract_broadcaster_ids_from_data({"no_data": []})
    assert result == set()


@pytest.mark.asyncio
async def test_extract_broadcaster_id_wrong_type():
    """Test _extract_broadcaster_id handles wrong subscription type."""
    backend = EventSubChatBackend()

    entry = {"type": "wrong_type", "transport": {"session_id": "session123"}, "condition": {"broadcaster_user_id": "123"}}
    result = backend._extract_broadcaster_id(entry)
    assert result is None


@pytest.mark.asyncio
async def test_extract_broadcaster_id_wrong_session():
    """Test _extract_broadcaster_id handles wrong session_id."""
    backend = EventSubChatBackend()
    backend._session_id = "session123"

    entry = {"type": "channel.chat.message", "transport": {"session_id": "wrong_session"}, "condition": {"broadcaster_user_id": "123"}}
    result = backend._extract_broadcaster_id(entry)
    assert result is None


@pytest.mark.asyncio
async def test_resubscribe_missing_no_channels():
    """Test _resubscribe_missing when no channels match."""
    backend = EventSubChatBackend()
    backend._channel_ids = {"chan1": "123"}
    backend._channels = ["chan1"]

    backend._subscribe_channel_chat = AsyncMock()
    await backend._resubscribe_missing({"999"})
    backend._subscribe_channel_chat.assert_not_called()
