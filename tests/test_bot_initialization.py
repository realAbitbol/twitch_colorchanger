from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from src.bot.core import TwitchColorBot
from src.errors.internal import InternalError


@pytest.mark.asyncio
async def test_bot_init():
    """Test TwitchColorBot.__init__ sets attributes correctly."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
        is_prime_or_turbo=True,
        config_file="test.conf",
        user_id="123",
        enabled=True,
    )
    assert bot.context == ctx
    assert bot.username == "testuser"
    assert bot.access_token == "test_token"
    assert bot.refresh_token == "test_refresh"
    assert bot.client_id == "test_client_id"
    assert bot.client_secret == "test_client_secret"
    assert bot.user_id == "123"
    assert bot.channels == ["#test"]
    assert bot.use_random_colors is True
    assert bot.config_file == "test.conf"
    assert bot.enabled is True
    assert bot.http_session == session
    assert bot.running is False
    assert bot.messages_sent == 0
    assert bot.colors_changed == 0
    assert bot.last_color is None


@pytest.mark.asyncio
async def test_initialize_connection_success():
    """Test _initialize_connection success path."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"  # Pre-set to avoid _ensure_user_id

    with patch.object(bot, "_ensure_user_id", return_value=True) as mock_ensure, \
          patch.object(bot, "_prime_color_state") as mock_prime, \
          patch.object(bot, "_log_scopes_if_possible") as mock_log, \
          patch.object(bot, "_normalize_channels_if_needed", return_value=["#test"]) as mock_norm, \
          patch.object(bot, "_init_and_connect_backend", return_value=True) as mock_init:
        result = await bot._initialize_connection()

        assert result is True
        mock_ensure.assert_called_once()
        mock_prime.assert_called_once()
        mock_log.assert_called_once()
        mock_norm.assert_called_once()
        mock_init.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_connection_ensure_user_id_fails():
    """Test _initialize_connection when _ensure_user_id fails."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot, "_ensure_user_id", return_value=False) as mock_ensure:
        result = await bot._initialize_connection()

        assert result is False
        mock_ensure.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_connection_backend_connect_fails():
    """Test _initialize_connection when backend connect fails."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    with patch.object(bot, "_ensure_user_id", return_value=True), \
          patch.object(bot, "_prime_color_state"), \
          patch.object(bot, "_log_scopes_if_possible"), \
          patch.object(bot, "_normalize_channels_if_needed", return_value=["#test"]), \
          patch.object(bot, "_init_and_connect_backend", return_value=False) as mock_init:
        result = await bot._initialize_connection()

        assert result is False
        mock_init.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_user_id_already_set():
    """Test _ensure_user_id when user_id is already set."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    result = await bot._ensure_user_id()

    assert result is True
    assert bot.user_id == "123"


@pytest.mark.asyncio
async def test_ensure_user_id_success():
    """Test _ensure_user_id success from API."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot, "_get_user_info", return_value={"id": "456"}) as mock_get:
        result = await bot._ensure_user_id()

        assert result is True
        assert bot.user_id == "456"
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_user_id_failure():
    """Test _ensure_user_id failure from API."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot, "_get_user_info", return_value=None) as mock_get:
        result = await bot._ensure_user_id()

        assert result is False
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prime_color_state_success():
    """Test _prime_color_state success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot, "_get_current_color", return_value="red") as mock_get:
        await bot._prime_color_state()

        assert bot.last_color == "red"
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prime_color_state_failure():
    """Test _prime_color_state failure."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot, "_get_current_color", return_value=None) as mock_get:
        await bot._prime_color_state()

        assert bot.last_color is None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_success():
    """Test _log_scopes_if_possible success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    ctx.session = session
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    # Updated patch path to src.bot.token_refresher.TwitchAPI to match import location
    with patch("src.bot.token_refresher.TwitchAPI") as mock_api_class:
        mock_api = MagicMock()
        mock_api.validate_token = AsyncMock(return_value={"scopes": ["user:read:chat", "user:manage:chat_color"]})
        mock_api_class.return_value = mock_api

        await bot._log_scopes_if_possible()

        mock_api.validate_token.assert_called_once_with("test_token")


@pytest.mark.asyncio
async def test_log_scopes_if_possible_no_session():
    """Test _log_scopes_if_possible when no session."""
    ctx = MagicMock()
    ctx.session = None
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    # Should not raise, just debug log
    await bot._log_scopes_if_possible()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_validation_fails():
    """Test _log_scopes_if_possible when validation fails."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    ctx.session = session
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    # Updated patch path to src.bot.token_refresher.TwitchAPI to match import location
    with patch("src.bot.token_refresher.TwitchAPI") as mock_api_class:
        mock_api = MagicMock()
        mock_api.validate_token = AsyncMock(side_effect=ValueError("Validation failed"))
        mock_api_class.return_value = mock_api

        await bot._log_scopes_if_possible()

        mock_api.validate_token.assert_called_once_with("test_token")


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_changed():
    """Test _normalize_channels_if_needed when channels are changed."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["test", "Test2"],
        http_session=session,
    )

    # Updated patch path to src.bot.token_refresher.normalize_channels_list to match import location
    with patch("src.bot.token_refresher.normalize_channels_list", return_value=(["#test", "#test2"], True)) as mock_norm, \
          patch.object(bot, "_persist_normalized_channels", new_callable=AsyncMock) as mock_persist:
        result = await bot._normalize_channels_if_needed()

        assert result == ["#test", "#test2"]
        assert bot.channels == ["#test", "#test2"]
        mock_norm.assert_called_once_with(["#test", "#Test2"])
        mock_persist.assert_called_once()


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_no_change():
    """Test _normalize_channels_if_needed when no change."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    # Updated patch path to src.bot.token_refresher.normalize_channels_list to match import location
    with patch("src.bot.token_refresher.normalize_channels_list", return_value=(["#test"], False)) as mock_norm, \
          patch.object(bot, "_persist_normalized_channels", new_callable=AsyncMock) as mock_persist:
        result = await bot._normalize_channels_if_needed()

        assert result == ["#test"]
        assert bot.channels == ["#test"]
        mock_norm.assert_called_once_with(["#test"])
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_init_and_connect_backend_success():
    """Test _init_and_connect_backend success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    ctx.session = session
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    with patch("src.bot.core.EventSubChatBackend") as mock_backend_class:
        mock_backend = MagicMock()
        mock_backend.connect = AsyncMock(return_value=True)
        mock_backend.set_message_handler = MagicMock()
        mock_backend.set_token_invalid_callback = MagicMock()
        mock_backend_class.return_value = mock_backend

        result = await bot._init_and_connect_backend(["#test"])

        assert result is True
        mock_backend_class.assert_called_once_with(http_session=session)
        mock_backend.connect.assert_called_once_with(
            "test_token", "testuser", "#test", "123", "test_client_id", "test_client_secret"
        )


@pytest.mark.asyncio
async def test_init_and_connect_backend_connect_fails():
    """Test _init_and_connect_backend when connect fails."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    ctx.session = session
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    with patch("src.bot.core.EventSubChatBackend") as mock_backend_class:
        mock_backend = MagicMock()
        mock_backend.connect = AsyncMock(return_value=False)
        mock_backend.set_message_handler = MagicMock()
        mock_backend.set_token_invalid_callback = MagicMock()
        mock_backend_class.return_value = mock_backend

        result = await bot._init_and_connect_backend(["#test"])

        assert result is False
        mock_backend.connect.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_info_impl_success():
    """Test _get_user_info_impl success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot.api, "request") as mock_request:
        mock_request.return_value = ({"data": [{"id": "123", "login": "testuser"}]}, 200, {})
        result = await bot._get_user_info_impl()

        assert result == {"id": "123", "login": "testuser"}
        mock_request.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_info_impl_401():
    """Test _get_user_info_impl 401 error."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot.api, "request") as mock_request:
        mock_request.return_value = (None, 401, {})
        with pytest.raises(InternalError):
            await bot._get_user_info_impl()


@pytest.mark.asyncio
async def test_get_user_info_impl_retry_success():
    """Test _get_user_info_impl retry on 429."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch.object(bot.api, "request") as mock_request, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_request.side_effect = [
            (None, 429, {}),
            ({"data": [{"id": "123"}]}, 200, {})
        ]
        result = await bot._get_user_info_impl()

        assert result == {"id": "123"}
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_color_impl_success():
    """Test _get_current_color_impl success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    with patch.object(bot.api, "request") as mock_request:
        mock_request.return_value = ({"data": [{"color": "red"}]}, 200, {})
        result = await bot._get_current_color_impl()

        assert result == "red"
        mock_request.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_color_impl_401():
    """Test _get_current_color_impl 401 error."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )
    bot.user_id = "123"

    with patch.object(bot.api, "request") as mock_request:
        mock_request.return_value = (None, 401, {})
        with pytest.raises(InternalError):
            await bot._get_current_color_impl()


@pytest.mark.asyncio
async def test_persist_token_changes_success():
    """Test _persist_token_changes success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
        config_file="test.conf",
    )

    # Updated patch path to src.bot.token_refresher.async_update_user_in_config to match import location
    with patch("src.bot.token_refresher.async_update_user_in_config", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = True
        await bot._persist_token_changes()

        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_persist_token_changes_no_config():
    """Test _persist_token_changes no config file."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    # Should not raise
    await bot._persist_token_changes()


@pytest.mark.asyncio
async def test_persist_token_changes_update_fails():
    """Test _persist_token_changes when update fails."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
        config_file="test.conf",
    )

    # Updated patch path to src.bot.token_refresher.async_update_user_in_config to match import location
    with patch("src.bot.token_refresher.async_update_user_in_config", new_callable=AsyncMock) as mock_update, \
          patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_update.return_value = False
        await bot._persist_token_changes()

        assert mock_update.call_count == 3  # retries
        mock_sleep.assert_called()


@pytest.mark.asyncio
async def test_change_color_success():
    """Test _change_color success."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch("src.color.ColorChangeService") as mock_svc_class:
        mock_svc = MagicMock()
        mock_svc.change_color = AsyncMock(return_value=True)
        mock_svc_class.return_value = mock_svc

        result = await bot._change_color("red")

        assert result is True
        mock_svc.change_color.assert_called_once_with("red")


@pytest.mark.asyncio
async def test_change_color_no_arg():
    """Test _change_color with no argument."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    with patch("src.color.ColorChangeService") as mock_svc_class:
        mock_svc = MagicMock()
        mock_svc.change_color = AsyncMock(return_value=True)
        mock_svc_class.return_value = mock_svc

        result = await bot._change_color()

        assert result is True
        mock_svc.change_color.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_is_color_change_allowed_enabled():
    """Test _is_color_change_allowed when enabled."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
        enabled=True,
    )

    result = bot._is_color_change_allowed()

    assert result is True


@pytest.mark.asyncio
async def test_is_color_change_allowed_disabled():
    """Test _is_color_change_allowed when disabled."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
        enabled=False,
    )

    result = bot._is_color_change_allowed()

    assert result is False


def test_normalize_color_arg_preset():
    """Test _normalize_color_arg with preset."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    result = bot._normalize_color_arg("Red")

    assert result == "red"


def test_normalize_color_arg_hex_6():
    """Test _normalize_color_arg with 6-digit hex."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    result = bot._normalize_color_arg("#aabbcc")

    assert result == "#aabbcc"


def test_normalize_color_arg_hex_3():
    """Test _normalize_color_arg with 3-digit hex."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    result = bot._normalize_color_arg("abc")

    assert result == "#aabbcc"


def test_normalize_color_arg_invalid():
    """Test _normalize_color_arg with invalid input."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    result = bot._normalize_color_arg("invalid")

    assert result is None


def test_normalize_color_arg_empty():
    """Test _normalize_color_arg with empty string."""
    ctx = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=session,
    )

    result = bot._normalize_color_arg("")

    assert result is None
