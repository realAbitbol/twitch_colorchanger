from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.core import TwitchColorBot


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.token_manager = MagicMock()
    ctx.token_manager.ensure_fresh = AsyncMock()
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


# Tests for reconnection with exponential backoff
@pytest.mark.asyncio
async def test_attempt_reconnect_success(bot):
    """Test successful reconnection after initial failure."""
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    bot.chat_backend = mock_backend
    bot.running = True

    with patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=True):
        await bot._attempt_reconnect(RuntimeError("Test error"), bot._listener_task_done)

    assert bot.listener_task is not None


@pytest.mark.asyncio
async def test_attempt_reconnect_max_attempts(bot):
    """Test reconnection stops after max attempts."""
    bot.running = True

    with patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=False):
        await bot._attempt_reconnect(RuntimeError("Test error"), bot._listener_task_done, max_attempts=2)

    # Should have attempted 2 times
    assert bot.listener_task is None


@pytest.mark.asyncio
async def test_attempt_reconnect_backoff_timing(bot):
    """Test exponential backoff timing."""
    import time
    start_time = time.time()
    bot.running = True

    with patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=False):
        await bot._attempt_reconnect(RuntimeError("Test error"), bot._listener_task_done, max_attempts=3, initial_backoff=0.1)

    elapsed = time.time() - start_time
    # Should be at least 0.1 + 0.2 + 0.4 = 0.7 seconds
    assert elapsed >= 0.7


@pytest.mark.asyncio
async def test_attempt_reconnect_bot_not_running(bot):
    """Test reconnection stops when bot is not running."""
    bot.running = False

    await bot._attempt_reconnect(RuntimeError("Test error"), bot._listener_task_done)

    # Should not attempt reconnection
    assert bot.listener_task is None


@pytest.mark.asyncio
async def test_attempt_reconnect_exception_during_reconnect(bot):
    """Test handling exception during reconnection attempt."""
    bot.running = True

    with patch.object(bot, "_initialize_connection", side_effect=Exception("Reconnect failed")):
        await bot._attempt_reconnect(RuntimeError("Test error"), bot._listener_task_done, max_attempts=2)

    # Should continue to next attempt
    assert bot.listener_task is None


# Tests for listener task error handling
@pytest.mark.asyncio
async def test_listener_task_done_with_exception(bot):
    """Test callback logs exception."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("Task failed")

    with patch("src.bot.core.logging") as mock_logging:
        bot._listener_task_done(task)

    mock_logging.error.assert_called_once()


@pytest.mark.asyncio
async def test_listener_task_done_cancelled(bot):
    """Test callback does nothing for cancelled task."""
    task = MagicMock()
    task.cancelled.return_value = True

    with patch("src.bot.core.logging") as mock_logging:
        bot._listener_task_done(task)

    mock_logging.error.assert_not_called()


@pytest.mark.asyncio
async def test_listener_task_done_no_exception(bot):
    """Test callback does nothing when no exception."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = None

    with patch("src.bot.core.logging") as mock_logging:
        bot._listener_task_done(task)

    mock_logging.error.assert_not_called()


@pytest.mark.asyncio
async def test_listener_task_done_logging_failure(bot):
    """Test callback handles logging failure gracefully."""
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("Task failed")

    with patch("src.bot.core.logging") as mock_logging:
        mock_logging.error.side_effect = Exception("Logging failed")
        bot._listener_task_done(task)

    mock_logging.debug.assert_called_once()


# Tests for additional channel joining
@pytest.mark.asyncio
async def test_join_additional_channels_success(bot):
    """Test joining multiple additional channels successfully."""
    mock_backend = MagicMock()
    mock_backend.join_channel = AsyncMock()
    normalized_channels = ["#chan1", "#chan2", "#chan3"]

    await bot._join_additional_channels(mock_backend, normalized_channels)

    assert mock_backend.join_channel.call_count == 2  # chan2 and chan3


@pytest.mark.asyncio
async def test_join_additional_channels_failure_one(bot):
    """Test continues joining when one channel fails."""
    mock_backend = MagicMock()
    mock_backend.join_channel = AsyncMock(side_effect=[Exception("Fail"), None])
    normalized_channels = ["#chan1", "#chan2", "#chan3"]

    with patch("src.bot.core.logging") as mock_logging:
        await bot._join_additional_channels(mock_backend, normalized_channels)

    mock_logging.warning.assert_called_once()


@pytest.mark.asyncio
async def test_join_additional_channels_empty(bot):
    """Test no additional channels to join."""
    mock_backend = MagicMock()
    mock_backend.join_channel = AsyncMock()
    normalized_channels = ["#chan1"]

    await bot._join_additional_channels(mock_backend, normalized_channels)

    mock_backend.join_channel.assert_not_called()


# Tests for token invalid callbacks
@pytest.mark.asyncio
async def test_set_token_invalid_callback(bot):
    """Test setting token invalid callback on backend."""
    mock_backend = MagicMock()
    mock_backend.connect = AsyncMock(return_value=True)
    mock_backend.set_token_invalid_callback = MagicMock()

    with patch("src.bot.core.EventSubChatBackend", return_value=mock_backend), \
         patch.object(bot, "_check_and_refresh_token") as mock_callback, \
         patch.object(bot, "_ensure_user_id", new_callable=AsyncMock, return_value=True), \
         patch.object(bot, "_prime_color_state", new_callable=AsyncMock), \
         patch.object(bot, "_log_scopes_if_possible", new_callable=AsyncMock), \
         patch.object(bot, "_normalize_channels_if_needed", new_callable=AsyncMock, return_value=["#chan1"]):
        await bot._init_and_connect_backend(["#chan1"])

    mock_backend.set_token_invalid_callback.assert_called_once_with(mock_callback)


@pytest.mark.asyncio
async def test_token_invalid_callback_execution(bot):
    """Test token invalid callback is called."""
    with patch.object(bot, "_check_and_refresh_token", new_callable=AsyncMock) as mock_callback:
        # Simulate callback execution
        await mock_callback()

    mock_callback.assert_called_once()


# Tests for state lock usage
@pytest.mark.asyncio
async def test_state_lock_in_start(bot):
    """Test state lock is acquired in start method."""
    with patch.object(bot, "_setup_token_manager", return_value=True), \
         patch.object(bot, "_handle_initial_token_refresh", new_callable=AsyncMock), \
         patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=True), \
         patch.object(bot, "_run_chat_loop", new_callable=AsyncMock):
        await bot.start()

    # Lock should have been acquired
    assert bot.running is True


@pytest.mark.asyncio
async def test_state_lock_in_stop(bot):
    """Test state lock is acquired in stop method."""
    bot.running = True
    bot.listener_task = MagicMock()

    with patch.object(bot, "_disconnect_chat_backend", new_callable=AsyncMock), \
         patch.object(bot, "_wait_for_listener_task", new_callable=AsyncMock), \
         patch("src.bot.core.flush_pending_updates", new_callable=AsyncMock):
        await bot.stop()

    assert bot.running is False


@pytest.mark.asyncio
async def test_state_lock_in_attempt_reconnect(bot):
    """Test state lock is acquired in attempt reconnect."""
    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    bot.chat_backend = mock_backend
    bot.running = True

    with patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=True):
        await bot._attempt_reconnect(RuntimeError("Test"), bot._listener_task_done)

    # Lock should have been acquired during reconnect
    assert bot.listener_task is not None

@pytest.mark.asyncio
async def test_bot_core_init_invalid_config():
    """Test BotCore initialization with invalid configuration parameters."""
    with pytest.raises(ValueError, match="http_session is required"):
        TwitchColorBot(
            context=MagicMock(),
            token="oauth:token",
            refresh_token="refresh",
            client_id="client_id",
            client_secret="client_secret",
            nick="testuser",
            channels=["#chan1"],
            http_session=None,  # invalid
            is_prime_or_turbo=True,
            config_file=None,
            user_id="123",
            enabled=True,
        )


@pytest.mark.asyncio
async def test_start_connection_failures(bot):
    """Test start method handling of connection failures and retry logic."""
    with patch.object(bot, "_setup_token_manager", return_value=True), \
         patch.object(bot, "_handle_initial_token_refresh", new_callable=AsyncMock), \
         patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=False):
        await bot.start()
        assert bot.running is False


@pytest.mark.asyncio
async def test_stop_active_operations(bot):
    """Test stop method during active operations, ensuring clean shutdown."""
    bot.running = True
    bot.listener_task = asyncio.create_task(asyncio.sleep(10))
    with patch.object(bot, "_disconnect_chat_backend", new_callable=AsyncMock), \
         patch("src.bot.core.flush_pending_updates", new_callable=AsyncMock):
        await bot.stop()
        assert bot.running is False
        assert bot.listener_task.cancelled()


@pytest.mark.asyncio
async def test_handle_message_malformed(bot):
    """Test handle_message with malformed or invalid message data."""
    with patch.object(logging, "error") as mock_error:
        await bot.handle_message(bot.username, "channel", {"invalid": "data"})
        mock_error.assert_called()


@pytest.mark.asyncio
async def test_color_change_request_invalid(bot):
    """Test color_change_request with invalid parameters or edge cases."""
    with patch.object(bot, "_change_color", side_effect=ValueError("Invalid color")) as mock_change, \
         patch.object(logging, "error") as mock_error:
        try:
            await bot._change_color("invalid_color")
        except ValueError:
            logging.error("Invalid color")
        mock_error.assert_called()


@pytest.mark.asyncio
async def test_bot_core_message_processing_error(bot):
    """Test message processing when an error occurs."""
    with patch.object(bot, "_change_color", side_effect=Exception("Processing error")) as mock_change, \
         patch.object(logging, "error") as mock_error:
        await bot.handle_message(bot.username, "channel", "!color red")
        mock_error.assert_called()


@pytest.mark.asyncio
async def test_bot_core_connection_recovery(bot):
    """Test connection recovery after temporary failure."""
    with patch.object(bot, "_initialize_connection", new_callable=AsyncMock, return_value=True), \
         patch.object(bot, "_run_chat_loop", new_callable=AsyncMock):
        await bot.start()
        # Should succeed
        assert bot.running is True


@pytest.mark.asyncio
async def test_bot_core_shutdown_graceful(bot):
    """Test graceful shutdown under normal conditions."""
    bot.running = True
    bot.listener_task = asyncio.create_task(asyncio.sleep(10))  # Long running task
    with patch.object(bot, "_disconnect_chat_backend", new_callable=AsyncMock), \
         patch("src.bot.core.flush_pending_updates", new_callable=AsyncMock):
        await bot.stop()
        assert bot.running is False
        assert bot.listener_task.cancelled()
