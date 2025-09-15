from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.connection_manager import ConnectionManager
from src.bot.core import TwitchColorBot


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.token_manager = MagicMock()
    ctx.token_manager.ensure_fresh = MagicMock()
    ctx.token_manager.get_info = MagicMock()
    return ctx


@pytest.fixture
def mock_http_session():
    return MagicMock()


@pytest.fixture
def bot(mock_context, mock_http_session):
    return TwitchColorBot(
        context=mock_context,
        token="oauth:token",
        refresh_token="refresh",
        client_id="client_id",
        client_secret="client_secret",
        nick="testuser",
        channels=["#chan1", "#chan2"],
        http_session=mock_http_session,
        is_prime_or_turbo=True,
        config_file=None,
        user_id="123",
        enabled=True,
    )


@pytest.fixture
def connection_manager(bot):
    return ConnectionManager(bot)


@pytest.mark.asyncio
async def test_initialize_connection_user_id_failure(connection_manager, bot):
    """Test initialize_connection when _ensure_user_id fails."""
    with patch.object(connection_manager, "_ensure_user_id", return_value=False):
        result = await connection_manager.initialize_connection()
        assert result is False


@pytest.mark.asyncio
async def test_initialize_connection_backend_connect_failure(connection_manager, bot):
    """Test initialize_connection when backend connection fails."""
    with patch.object(connection_manager, "_ensure_user_id", return_value=True), \
         patch.object(connection_manager, "_prime_color_state"), \
         patch.object(connection_manager, "_log_scopes_if_possible"), \
         patch.object(connection_manager, "_normalize_channels_if_needed", return_value=["#chan1"]), \
         patch.object(connection_manager, "_init_and_connect_backend", return_value=False):
        result = await connection_manager.initialize_connection()
        assert result is False


@pytest.mark.asyncio
async def test_run_chat_loop_reconnection_success(connection_manager, bot):
    """Test run_chat_loop with successful reconnection."""
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    connection_manager.chat_backend = mock_backend
    connection_manager._normalized_channels_cache = ["#chan1"]

    with patch.object(connection_manager, "_join_additional_channels"), \
         patch.object(connection_manager, "_attempt_reconnect", new_callable=AsyncMock) as mock_reconnect:
        # Simulate exception in listener
        mock_backend.listen.side_effect = RuntimeError("Test error")
        await connection_manager.run_chat_loop()
        mock_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_run_chat_loop_reconnection_exhaustion(connection_manager, bot):
    """Test run_chat_loop when reconnection exhausts attempts."""
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    connection_manager.chat_backend = mock_backend
    connection_manager._normalized_channels_cache = ["#chan1"]

    with patch.object(connection_manager, "_join_additional_channels"), \
         patch.object(connection_manager, "_attempt_reconnect", new_callable=AsyncMock) as mock_reconnect:
        mock_reconnect.side_effect = RuntimeError("Reconnect failed")
        mock_backend.listen.side_effect = RuntimeError("Test error")
        with pytest.raises(RuntimeError):
            await connection_manager.run_chat_loop()
        mock_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_attempt_reconnect_keyboard_interrupt(connection_manager, bot):
    """Test _attempt_reconnect handles exceptions."""
    bot.running = True
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock(side_effect=ValueError("Test"))
    connection_manager.chat_backend = mock_backend

    with patch.object(connection_manager, "initialize_connection", new_callable=AsyncMock, return_value=True), \
         patch("asyncio.sleep"):
        await connection_manager._attempt_reconnect(RuntimeError("Test"), connection_manager._listener_task_done, max_attempts=1)


@pytest.mark.asyncio
async def test_join_additional_channels_partial_failure(connection_manager, bot):
    """Test _join_additional_channels with partial failures."""
    mock_backend = MagicMock()
    mock_backend.join_channel = AsyncMock(side_effect=[Exception("Fail"), None])
    normalized_channels = ["#chan1", "#chan2", "#chan3"]

    with patch("src.bot.connection_manager.logging") as mock_logging:
        await connection_manager._join_additional_channels(mock_backend, normalized_channels)
        mock_logging.warning.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_listener_task_timeout(connection_manager, bot):
    """Test wait_for_listener_task with timeout."""
    task = asyncio.create_task(asyncio.sleep(10))
    connection_manager.listener_task = task

    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await connection_manager.wait_for_listener_task()
        assert task.cancelling()


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_invalid_channels(connection_manager, bot):
    """Test _normalize_channels_if_needed with invalid channels."""
    bot.channels = ["invalid", "#valid"]
    with patch("src.config.model.normalize_channels_list", return_value=(["#valid"], True)), \
         patch.object(connection_manager, "_persist_normalized_channels"):
        result = await connection_manager._normalize_channels_if_needed()
        assert result == ["#valid"]


@pytest.mark.asyncio
async def test_persist_normalized_channels_config_error(connection_manager, bot):
    """Test _persist_normalized_channels with config error."""
    bot.config_file = "test.json"
    user_config = {"channels": ["#chan1"]}
    with patch.object(connection_manager.bot, "_build_user_config", return_value=user_config), \
         patch("src.config.async_persistence.queue_user_update", side_effect=OSError("Config error")), \
         patch("src.bot.connection_manager.logging") as mock_logging:
        await connection_manager._persist_normalized_channels()
        mock_logging.warning.assert_called_once_with("Persist channels error: Config error")


@pytest.mark.asyncio
async def test_ensure_user_id_success(connection_manager, bot):
    """Test _ensure_user_id success."""
    bot.user_id = None
    with patch.object(bot, "_get_user_info", return_value={"id": "123"}):
        result = await connection_manager._ensure_user_id()
        assert result is True
        assert bot.user_id == "123"


@pytest.mark.asyncio
async def test_ensure_user_id_failure(connection_manager, bot):
    """Test _ensure_user_id failure."""
    bot.user_id = None
    with patch.object(bot, "_get_user_info", return_value=None):
        result = await connection_manager._ensure_user_id()
        assert result is False


@pytest.mark.asyncio
async def test_prime_color_state(connection_manager, bot):
    """Test _prime_color_state."""
    with patch.object(bot, "_get_current_color", return_value="red"):
        await connection_manager._prime_color_state()
        assert bot.last_color == "red"


@pytest.mark.asyncio
async def test_log_scopes_if_possible_success(connection_manager, bot):
    """Test _log_scopes_if_possible success."""
    with patch("src.api.twitch.TwitchAPI") as mock_api, \
         patch("src.errors.handling.handle_api_error") as mock_handle:
        mock_api.return_value.validate_token.return_value = {"scopes": ["chat:read"]}
        mock_handle.return_value = {"scopes": ["chat:read"]}
        await connection_manager._log_scopes_if_possible()
        mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_no_session(connection_manager, bot):
    """Test _log_scopes_if_possible with no session."""
    bot.context.session = None
    await connection_manager._log_scopes_if_possible()
    # No assertions needed, just ensure no exception


@pytest.mark.asyncio
async def test_log_scopes_if_possible_validation_error(connection_manager, bot):
    """Test _log_scopes_if_possible with validation error."""
    with patch("src.api.twitch.TwitchAPI"), \
         patch("src.errors.handling.handle_api_error", side_effect=ValueError("Validation error")):
        await connection_manager._log_scopes_if_possible()
        # No assertions needed, just ensure no exception

@pytest.mark.asyncio
async def test_normalize_channels_if_needed_no_change(connection_manager, bot):
    """Test _normalize_channels_if_needed when no change is needed."""
    bot.channels = ["#chan1"]
    with patch("src.config.model.normalize_channels_list", return_value=(["#chan1"], False)):
        result = await connection_manager._normalize_channels_if_needed()
        assert result == ["#chan1"]


@pytest.mark.asyncio
async def test_persist_normalized_channels_success(connection_manager, bot):
    """Test _persist_normalized_channels success."""
    bot.config_file = "test.json"
    bot.channels = ["#chan1"]
    with patch.object(connection_manager.bot, "_build_user_config", return_value={"channels": ["#chan1"]}), \
         patch("src.config.async_persistence.queue_user_update", new_callable=AsyncMock) as mock_queue:
        await connection_manager._persist_normalized_channels()
        mock_queue.assert_called_once()


@pytest.mark.asyncio
async def test_persist_normalized_channels_no_config(connection_manager, bot):
    """Test _persist_normalized_channels with no config file."""
    bot.config_file = None
    await connection_manager._persist_normalized_channels()
    # No action expected


@pytest.mark.asyncio
async def test_init_and_connect_backend_success(connection_manager, bot):
    """Test _init_and_connect_backend success."""
    with patch("src.chat.EventSubChatBackend") as mock_backend_class, \
         patch.object(connection_manager.bot, "token_manager"):
        mock_backend = MagicMock()
        mock_backend.set_message_handler = MagicMock()
        mock_backend.connect = AsyncMock(return_value=True)
        mock_backend_class.return_value = mock_backend
        result = await connection_manager._init_and_connect_backend(["#chan1"])
        assert result is True
        mock_backend.connect.assert_called_once()


@pytest.mark.asyncio
async def test_init_and_connect_backend_failure(connection_manager, bot):
    """Test _init_and_connect_backend failure."""
    with patch("src.chat.EventSubChatBackend") as mock_backend_class:
        mock_backend = MagicMock()
        mock_backend.connect = AsyncMock(return_value=False)
        mock_backend_class.return_value = mock_backend
        result = await connection_manager._init_and_connect_backend(["#chan1"])
        assert result is False


@pytest.mark.asyncio
async def test_create_and_monitor_listener(connection_manager, bot):
    """Test _create_and_monitor_listener."""
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    mock_task = MagicMock()
    with patch("asyncio.create_task", return_value=mock_task):
        connection_manager._create_and_monitor_listener(mock_backend)
        assert connection_manager.listener_task is not None
        mock_task.add_done_callback.assert_called_once()


def test_listener_task_done_success(connection_manager, bot):
    """Test _listener_task_done with successful task."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = None
    connection_manager._listener_task_done(task)
    # No logging expected


def test_listener_task_done_exception(connection_manager, bot):
    """Test _listener_task_done with exception."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("Test error")
    with patch("src.bot.connection_manager.logging") as mock_logging:
        connection_manager._listener_task_done(task)
        mock_logging.error.assert_called_once()
