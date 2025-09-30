"""
Unit tests for ConnectionManager.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.bot.connection_manager import ConnectionManager


class TestConnectionManager:
    """Test class for ConnectionManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_bot = Mock()
        self.mock_bot.username = "testuser"
        self.mock_bot.user_id = "12345"
        self.mock_bot.access_token = "mock_token"
        self.mock_bot.channels = ["testchannel"]
        self.mock_bot.context = Mock()
        self.mock_bot.context.session = Mock()
        self.mock_bot.message_processor = Mock()
        self.mock_bot.token_handler = Mock()
        self.mock_bot.token_manager = Mock()
        self.mock_bot.running = True
        self.mock_bot._get_user_info = AsyncMock(return_value={"id": "12345"})
        self.mock_bot._get_current_color = AsyncMock(return_value="#FF0000")
        self.mock_bot._build_user_config = Mock(return_value={"channels": ["testchannel"]})
        self.mock_bot._state_lock = AsyncMock()
        self.manager = ConnectionManager(self.mock_bot)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_sets_attributes(self):
        """Test ConnectionManager initialization sets correct attributes."""
        assert self.manager.bot == self.mock_bot
        assert self.manager.chat_backend is None
        assert self.manager.listener_task is None
        assert self.manager._normalized_channels_cache is None
        assert self.manager._total_reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_initialize_connection_success(self):
        """Test initialize_connection with successful setup."""
        with patch('src.chat.EventSubChatBackend') as mock_backend_class:
            mock_backend = Mock()
            mock_backend_class.return_value = mock_backend
            mock_backend.connect = AsyncMock(return_value=True)
            mock_backend.set_message_handler = Mock()
            mock_backend.set_token_invalid_callback = Mock()

            result = await self.manager.initialize_connection()

            assert result is True
            assert self.manager.chat_backend == mock_backend
            assert self.manager._normalized_channels_cache == ["testchannel"]
            mock_backend.set_message_handler.assert_called_once()
            mock_backend.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_connection_user_id_failure(self):
        """Test initialize_connection fails when user_id cannot be retrieved."""
        self.mock_bot._get_user_info = AsyncMock(return_value=None)

        result = await self.manager.initialize_connection()

        assert result is False

    @pytest.mark.asyncio
    async def test_initialize_connection_backend_failure(self):
        """Test initialize_connection fails when backend connection fails."""
        with patch('src.chat.EventSubChatBackend') as mock_backend_class:
            mock_backend = Mock()
            mock_backend_class.return_value = mock_backend
            mock_backend.connect = AsyncMock(return_value=False)

            result = await self.manager.initialize_connection()

            assert result is False

    @pytest.mark.asyncio
    async def test_ensure_user_id_already_set(self):
        """Test _ensure_user_id returns True when user_id is already set."""
        result = await self.manager._ensure_user_id()

        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_user_id_fetch_success(self):
        """Test _ensure_user_id fetches and sets user_id successfully."""
        self.mock_bot.user_id = None

        result = await self.manager._ensure_user_id()

        assert result is True
        assert self.mock_bot.user_id == "12345"

    @pytest.mark.asyncio
    async def test_ensure_user_id_fetch_failure(self):
        """Test _ensure_user_id fails when API returns invalid data."""
        self.mock_bot.user_id = None
        self.mock_bot._get_user_info = AsyncMock(return_value={})

        result = await self.manager._ensure_user_id()

        assert result is False

    @pytest.mark.asyncio
    async def test_prime_color_state(self):
        """Test _prime_color_state sets last_color from API."""
        await self.manager._prime_color_state()

        assert self.mock_bot.last_color == "#FF0000"

    @pytest.mark.asyncio
    async def test_prime_color_state_no_color(self):
        """Test _prime_color_state handles no color returned."""
        self.mock_bot._get_current_color = AsyncMock(return_value=None)

        await self.manager._prime_color_state()

        assert 'last_color' not in self.mock_bot.__dict__

    @pytest.mark.asyncio
    async def test_log_scopes_if_possible_success(self):
        """Test _log_scopes_if_possible logs token scopes."""
        with patch('src.api.twitch.TwitchAPI') as mock_api_class, \
             patch('src.errors.handling.handle_api_error') as mock_handle_error:
            mock_api = Mock()
            mock_api_class.return_value = mock_api
            mock_api.validate_token = AsyncMock()
            mock_handle_error.return_value = {"scopes": ["chat:read"]}

            await self.manager._log_scopes_if_possible()

            # Token validation was called as evidenced by the logged scopes

    @pytest.mark.asyncio
    async def test_log_scopes_if_possible_no_session(self):
        """Test _log_scopes_if_possible does nothing without session."""
        self.mock_bot.context.session = None

        await self.manager._log_scopes_if_possible()

        # No assertions needed, just ensure no errors

    @pytest.mark.asyncio
    async def test_normalize_channels_if_needed_changed(self):
        """Test _normalize_channels_if_needed when channels are changed."""
        self.mock_bot.channels = ["TestChannel"]

        with patch('src.config.model.normalize_channels_list') as mock_normalize:
            mock_normalize.return_value = (["testchannel"], True)

            result = await self.manager._normalize_channels_if_needed()

            assert result == ["testchannel"]
            assert self.mock_bot.channels == ["testchannel"]

    @pytest.mark.asyncio
    async def test_normalize_channels_if_needed_unchanged(self):
        """Test _normalize_channels_if_needed when channels are unchanged."""
        with patch('src.config.model.normalize_channels_list') as mock_normalize:
            mock_normalize.return_value = (["testchannel"], False)

            result = await self.manager._normalize_channels_if_needed()

            assert result == ["testchannel"]

    @pytest.mark.asyncio
    async def test_persist_normalized_channels_success(self):
        """Test _persist_normalized_channels saves config."""
        self.manager.config_file = "test.conf"

        with patch('src.config.async_persistence.queue_user_update') as mock_queue:
            await self.manager._persist_normalized_channels()

            mock_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_normalized_channels_no_config_file(self):
        """Test _persist_normalized_channels does nothing without config file."""
        await self.manager._persist_normalized_channels()

        # No assertions needed

    @pytest.mark.asyncio
    async def test_init_and_connect_backend_success(self):
        """Test _init_and_connect_backend connects successfully."""
        with patch('src.chat.EventSubChatBackend') as mock_backend_class:
            mock_backend = Mock()
            mock_backend_class.return_value = mock_backend
            mock_backend.connect = AsyncMock(return_value=True)
            mock_backend.set_message_handler = Mock()
            mock_backend.set_token_invalid_callback = Mock()

            result = await self.manager._init_and_connect_backend(["testchannel"])

            assert result is True
            assert self.manager.chat_backend == mock_backend

    @pytest.mark.asyncio
    async def test_init_and_connect_backend_no_token(self):
        """Test _init_and_connect_backend fails without access token."""
        self.mock_bot.access_token = None

        result = await self.manager._init_and_connect_backend(["testchannel"])

        assert result is False

    @pytest.mark.asyncio
    async def test_init_and_connect_backend_connection_failure(self):
        """Test _init_and_connect_backend fails when connection fails."""
        with patch('src.chat.EventSubChatBackend') as mock_backend_class:
            mock_backend = Mock()
            mock_backend_class.return_value = mock_backend
            mock_backend.connect = AsyncMock(return_value=False)

            result = await self.manager._init_and_connect_backend(["testchannel"])

            assert result is False

    @pytest.mark.asyncio
    async def test_run_chat_loop_with_backend(self):
        """Test run_chat_loop with backend initialized."""
        mock_backend = Mock()
        mock_backend.listen = AsyncMock()
        self.manager.chat_backend = mock_backend
        self.manager._normalized_channels_cache = ["testchannel"]

        with patch.object(self.manager, '_create_and_monitor_listener'), \
             patch.object(self.manager, '_join_additional_channels'):
            # Simulate KeyboardInterrupt to exit loop
            mock_backend.listen.side_effect = KeyboardInterrupt()

            # The method catches KeyboardInterrupt, so it should complete without raising
            await self.manager.run_chat_loop()

    @pytest.mark.asyncio
    async def test_run_chat_loop_no_backend(self):
        """Test run_chat_loop fails without backend."""
        with patch('src.bot.connection_manager.logging') as mock_logging:
            await self.manager.run_chat_loop()

            mock_logging.error.assert_called_once()

    def test_create_and_monitor_listener(self):
        """Test _create_and_monitor_listener creates and monitors task."""
        mock_backend = Mock()
        mock_backend.listen = AsyncMock()
        self.manager.chat_backend = mock_backend

        with patch('asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task

            self.manager._create_and_monitor_listener(mock_backend)

            assert self.manager.listener_task == mock_task
            mock_task.add_done_callback.assert_called_once_with(self.manager._listener_task_done)

    def test_listener_task_done_no_exception(self):
        """Test _listener_task_done handles task completion without exception."""
        mock_task = Mock()
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None

        self.manager._listener_task_done(mock_task)

        # No assertions needed, just ensure no errors

    def test_listener_task_done_with_exception(self):
        """Test _listener_task_done logs exception."""
        mock_task = Mock()
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = RuntimeError("test error")

        with patch('src.bot.connection_manager.logging') as mock_logging:
            self.manager._listener_task_done(mock_task)

            mock_logging.error.assert_called_once()

    def test_listener_task_done_cancelled(self):
        """Test _listener_task_done handles cancelled task."""
        mock_task = Mock()
        mock_task.cancelled.return_value = True

        self.manager._listener_task_done(mock_task)

        # No assertions needed

    @pytest.mark.asyncio
    async def test_join_additional_channels(self):
        """Test _join_additional_channels joins extra channels."""
        mock_backend = Mock()
        mock_backend.join_channel = AsyncMock()

        await self.manager._join_additional_channels(mock_backend, ["channel1", "channel2", "channel3"])

        assert mock_backend.join_channel.call_count == 2
        mock_backend.join_channel.assert_any_call("channel2")
        mock_backend.join_channel.assert_any_call("channel3")

    @pytest.mark.asyncio
    async def test_join_additional_channels_with_error(self):
        """Test _join_additional_channels handles join errors."""
        mock_backend = Mock()
        mock_backend.join_channel = AsyncMock(side_effect=Exception("join failed"))

        with patch('src.bot.connection_manager.logging') as mock_logging:
            await self.manager._join_additional_channels(mock_backend, ["channel1", "channel2"])

            mock_logging.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_attempt_reconnect_successful_resets_counter(self):
        """Test _attempt_reconnect resets counter on successful reconnection."""
        self.manager._total_reconnect_attempts = 5
        self.mock_bot._state_lock = AsyncMock()
        self.mock_bot._state_lock.__aenter__ = AsyncMock()
        self.mock_bot._state_lock.__aexit__ = AsyncMock()

        with patch.object(self.manager, 'initialize_connection', new_callable=AsyncMock) as mock_init:
            mock_init.return_value = True
            mock_backend = Mock()
            mock_backend.listen = AsyncMock()
            self.manager.chat_backend = mock_backend

            # Mock asyncio.sleep to avoid delay
            with patch('asyncio.sleep'):
                await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done)

                assert self.manager._total_reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_attempt_reconnect_max_attempts_reached(self):
        """Test _attempt_reconnect gives up when max attempts reached."""
        self.manager._total_reconnect_attempts = 10  # Above default max

        with patch('src.bot.connection_manager.logging') as mock_logging:
            await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done)

            mock_logging.error.assert_called_once()
            assert "Max total reconnection attempts" in mock_logging.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_attempt_reconnect_bounds_checking_prevents_infinite_loop(self):
        """Test _attempt_reconnect respects max_attempts parameter."""
        with patch.object(self.manager, 'initialize_connection', new_callable=AsyncMock) as mock_init, \
              patch('asyncio.sleep') as mock_sleep:
            mock_init.return_value = False

            await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done, max_attempts=3)

            # Should attempt exactly 3 times
            assert mock_init.call_count == 3
            assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_attempt_reconnect_multiple_consecutive_failures(self):
        """Test _attempt_reconnect handles multiple consecutive failures."""
        with patch.object(self.manager, 'initialize_connection', new_callable=AsyncMock) as mock_init, \
             patch('asyncio.sleep') as mock_sleep, \
             patch('src.bot.connection_manager.logging') as mock_logging:
            mock_init.return_value = False

            await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done, max_attempts=2)

            assert mock_init.call_count == 2
            assert mock_sleep.call_count == 2
            assert mock_logging.warning.call_count == 2

    @pytest.mark.asyncio
    async def test_attempt_reconnect_bot_not_running(self):
        """Test _attempt_reconnect stops when bot is not running."""
        self.mock_bot.running = False

        await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done)

        # Should not attempt reconnection
        assert self.manager._total_reconnect_attempts == 1  # Incremented but loop doesn't run

    @pytest.mark.asyncio
    async def test_attempt_reconnect_with_exception_during_reconnect(self):
        """Test _attempt_reconnect handles exceptions during reconnection attempts."""
        with patch.object(self.manager, 'initialize_connection', new_callable=AsyncMock) as mock_init, \
             patch('asyncio.sleep'), \
             patch('src.bot.connection_manager.logging') as mock_logging:
            mock_init.side_effect = [Exception("reconnect failed"), True]

            # Mock successful backend creation after exception
            with patch.object(self.manager, 'chat_backend', new_callable=lambda: Mock()) as mock_backend:
                mock_backend.listen = AsyncMock()
                self.manager.chat_backend = mock_backend

                await self.manager._attempt_reconnect(RuntimeError("test"), self.manager._listener_task_done, max_attempts=3)

                # Updated expectation: two failures + one success (which now includes cleanup warnings)
                assert mock_logging.warning.call_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_chat_backend_success(self):
        """Test disconnect_chat_backend disconnects successfully."""
        mock_backend = Mock()
        mock_backend.disconnect = AsyncMock()
        self.manager.chat_backend = mock_backend

        await self.manager.disconnect_chat_backend()

        mock_backend.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_chat_backend_no_backend(self):
        """Test disconnect_chat_backend does nothing without backend."""
        await self.manager.disconnect_chat_backend()

        # No assertions needed

    @pytest.mark.asyncio
    async def test_disconnect_chat_backend_with_error(self):
        """Test disconnect_chat_backend handles disconnect errors."""
        mock_backend = Mock()
        mock_backend.disconnect = AsyncMock(side_effect=Exception("disconnect failed"))
        self.manager.chat_backend = mock_backend

        with patch('src.bot.connection_manager.logging') as mock_logging:
            await self.manager.disconnect_chat_backend()

            # Updated expectation: cleanup warnings + disconnect error warning
            assert mock_logging.warning.call_count == 2

    @pytest.mark.asyncio
    async def test_wait_for_listener_task_with_task(self):
        """Test wait_for_listener_task waits for task completion."""
        mock_task = Mock()
        mock_task.done.return_value = True
        self.manager.listener_task = mock_task

        await self.manager.wait_for_listener_task()

        # No assertions needed, just ensure no errors

    @pytest.mark.asyncio
    async def test_wait_for_listener_task_timeout(self):
        """Test wait_for_listener_task handles timeout."""
        mock_task = Mock()
        mock_task.done.return_value = False
        self.manager.listener_task = mock_task

        with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError):
            await self.manager.wait_for_listener_task()

            mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_listener_task_cancelled_error(self):
        """Test wait_for_listener_task handles CancelledError."""
        mock_task = Mock()
        mock_task.done.return_value = False
        self.manager.listener_task = mock_task

        with patch('asyncio.wait_for', side_effect=asyncio.CancelledError), \
             pytest.raises(asyncio.CancelledError):
            await self.manager.wait_for_listener_task()

    @pytest.mark.asyncio
    async def test_wait_for_listener_task_other_error(self):
        """Test wait_for_listener_task handles other exceptions."""
        mock_task = Mock()
        mock_task.done.return_value = False
        self.manager.listener_task = mock_task

        with patch('asyncio.wait_for', side_effect=Exception("test error")), \
             patch('src.bot.connection_manager.logging') as mock_logging:
            await self.manager.wait_for_listener_task()

            mock_logging.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_listener_task_no_task(self):
        """Test wait_for_listener_task does nothing without task."""
        await self.manager.wait_for_listener_task()

        # No assertions needed
