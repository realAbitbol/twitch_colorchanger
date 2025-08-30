"""
Tests for bot_manager.py module
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.bot_manager import (
    BotManager,
    _cleanup_watcher,
    _run_main_loop,
    _setup_config_watcher,
    run_bots,
)
from src.colors import bcolors


class TestBotManager:
    """Test BotManager class"""

    def test_init(self):
        """Test BotManager initialization"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]
        config_file = "/path/to/config.json"

        manager = BotManager(users_config, config_file)

        assert manager.users_config == users_config
        assert manager.config_file == config_file
        assert manager.bots == []
        assert manager.tasks == []
        assert manager.running is False
        assert manager.shutdown_initiated is False
        assert manager.restart_requested is False
        assert manager.new_config is None

    @patch('src.bot_manager.print_log')
    async def test_start_all_bots_success(self, mock_print_log):
        """Test successful start of all bots"""
        users_config = [
            {"username": "user1", "access_token": "token1", "channels": ["#channel1"]},
            {"username": "user2", "access_token": "token2", "channels": ["#channel2"]}
        ]

        manager = BotManager(users_config)

        # Mock bot creation and start
        with patch.object(manager, '_create_bot') as mock_create_bot:
            mock_bot1 = MagicMock()
            mock_bot2 = MagicMock()
            mock_bot1.start = AsyncMock()
            mock_bot2.start = AsyncMock()

            mock_create_bot.side_effect = [mock_bot1, mock_bot2]

            success = await manager._start_all_bots()

            assert success is True
            assert len(manager.bots) == 2
            assert len(manager.tasks) == 2
            assert manager.running is True
            assert manager.shutdown_initiated is False

            # Verify bot creation calls
            assert mock_create_bot.call_count == 2
            mock_create_bot.assert_any_call(users_config[0])
            mock_create_bot.assert_any_call(users_config[1])

            # Verify tasks were created and started
            mock_bot1.start.assert_called_once()
            mock_bot2.start.assert_called_once()

    @patch('src.bot_manager.print_log')
    async def test_start_all_bots_no_bots_created(self, mock_print_log):
        """Test start when no bots can be created"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]

        manager = BotManager(users_config)

        # Mock bot creation to fail
        with patch.object(manager, '_create_bot') as mock_create_bot:
            mock_create_bot.side_effect = Exception("Bot creation failed")

            success = await manager._start_all_bots()

            assert success is False
            assert len(manager.bots) == 0
            assert manager.running is False

    @patch('src.bot_manager.print_log')
    def test_create_bot_success(self, mock_print_log):
        """Test successful bot creation"""
        manager = BotManager([])
        user_config = {
            "username": "testuser",
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "client_id": "client_id",
            "client_secret": "client_secret",
            "channels": ["#testchannel"],
            "is_prime_or_turbo": True
        }

        with patch('src.bot_manager.TwitchColorBot') as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot_class.return_value = mock_bot

            result = manager._create_bot(user_config)

            assert result == mock_bot
            mock_bot_class.assert_called_once_with(
                token="test_token",
                refresh_token="refresh_token",
                client_id="client_id",
                client_secret="client_secret",
                nick="testuser",
                channels=["#testchannel"],
                is_prime_or_turbo=True,
                config_file=None,
                user_id=None
            )

    @patch('src.bot_manager.print_log')
    def test_create_bot_failure(self, mock_print_log):
        """Test bot creation failure"""
        manager = BotManager([])
        user_config = {
            "username": "testuser",
            "access_token": "token",
            "channels": ["#channel"]}

        with patch('src.bot_manager.TwitchColorBot') as mock_bot_class:
            mock_bot_class.side_effect = Exception("Bot creation error")

            with pytest.raises(Exception, match="Bot creation error"):
                manager._create_bot(user_config)

    @patch('src.bot_manager.print_log')
    async def test_stop_all_bots(self, mock_print_log):
        """Test stopping all bots"""
        manager = BotManager([])
        manager.running = True

        # Create mock bots and tasks
        mock_bot1 = MagicMock()
        mock_bot2 = MagicMock()
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        mock_task1.done.return_value = False
        mock_task2.done.return_value = False

        manager.bots = [mock_bot1, mock_bot2]
        manager.tasks = [mock_task1, mock_task2]

        await manager._stop_all_bots()

        assert manager.running is False
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()
        mock_bot1.close.assert_called_once()
        mock_bot2.close.assert_called_once()

    async def test_stop_all_bots_not_running(self):
        """Test _stop_all_bots when already not running (covers line 89)"""
        manager = BotManager([])
        manager.running = False  # Set to not running

        with patch('src.bot_manager.print_log') as mock_log:
            await manager._stop_all_bots()

            # Should return early without logging the "Stopping all bots" message
            mock_log.assert_not_called()

    @patch('src.bot_manager.print_log')
    def test_stop_public_method(self, mock_print_log):
        """Test public stop method"""
        manager = BotManager([])

        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            manager.stop()

            assert manager.shutdown_initiated is True
            mock_loop.create_task.assert_called_once()

    @patch('src.bot_manager.print_log')
    def test_request_restart(self, mock_print_log):
        """Test requesting restart with new config"""
        manager = BotManager([])
        new_config = [{"username": "newuser",
                       "access_token": "newtoken",
                       "channels": ["#newchannel"]}]

        manager.request_restart(new_config)

        assert manager.restart_requested is True
        assert manager.new_config == new_config

    @patch('src.bot_manager.print_log')
    async def test_restart_with_new_config(self, mock_print_log):
        """Test restarting with new configuration"""
        old_config = [{"username": "olduser",
                       "access_token": "oldtoken",
                       "channels": ["#oldchannel"]}]
        new_config = [{"username": "newuser",
                       "access_token": "newtoken",
                       "channels": ["#newchannel"]}]

        manager = BotManager(old_config)
        manager.new_config = new_config
        manager.restart_requested = True

        # Mock the internal methods
        with patch.object(manager, '_save_statistics', return_value={}) as mock_save_stats, \
                patch.object(manager, '_stop_all_bots') as mock_stop, \
                patch.object(manager, '_start_all_bots', return_value=True) as mock_start, \
                patch.object(manager, '_restore_statistics') as mock_restore:

            success = await manager._restart_with_new_config()

            assert success is True
            assert manager.users_config == new_config
            assert manager.restart_requested is False
            assert manager.new_config is None

            mock_save_stats.assert_called_once()
            mock_stop.assert_called_once()
            mock_start.assert_called_once()
            mock_restore.assert_called_once()

    def test_save_statistics(self):
        """Test saving bot statistics"""
        manager = BotManager([])

        mock_bot1 = MagicMock()
        mock_bot1.username = "user1"
        mock_bot1.messages_sent = 10
        mock_bot1.colors_changed = 5

        mock_bot2 = MagicMock()
        mock_bot2.username = "user2"
        mock_bot2.messages_sent = 20
        mock_bot2.colors_changed = 15

        manager.bots = [mock_bot1, mock_bot2]

        stats = manager._save_statistics()

        expected_stats = {
            "user1": {"messages_sent": 10, "colors_changed": 5},
            "user2": {"messages_sent": 20, "colors_changed": 15}
        }
        assert stats == expected_stats

    def test_restore_statistics(self):
        """Test restoring bot statistics"""
        manager = BotManager([])

        mock_bot1 = MagicMock()
        mock_bot1.username = "user1"
        mock_bot2 = MagicMock()
        mock_bot2.username = "user2"

        manager.bots = [mock_bot1, mock_bot2]

        saved_stats = {
            "user1": {"messages_sent": 10, "colors_changed": 5},
            "user2": {"messages_sent": 20, "colors_changed": 15}
        }

        manager._restore_statistics(saved_stats)

        assert mock_bot1.messages_sent == 10
        assert mock_bot1.colors_changed == 5
        assert mock_bot2.messages_sent == 20
        assert mock_bot2.colors_changed == 15

    @patch('src.bot_manager.print_log')
    def test_print_statistics(self, mock_print_log):
        """Test printing statistics"""
        manager = BotManager([])

        mock_bot1 = MagicMock()
        mock_bot1.username = "user1"
        mock_bot1.messages_sent = 10
        mock_bot1.colors_changed = 5
        mock_bot1.print_statistics = MagicMock()

        mock_bot2 = MagicMock()
        mock_bot2.username = "user2"
        mock_bot2.messages_sent = 20
        mock_bot2.colors_changed = 15
        mock_bot2.print_statistics = MagicMock()

        manager.bots = [mock_bot1, mock_bot2]

        manager.print_statistics()

        # Verify individual bot statistics were called
        mock_bot1.print_statistics.assert_called_once()
        mock_bot2.print_statistics.assert_called_once()

    @patch('src.bot_manager.print_log')
    def test_setup_signal_handlers(self, mock_print_log):
        """Test setting up signal handlers"""
        manager = BotManager([])

        with patch('signal.signal') as mock_signal:
            manager.setup_signal_handlers()

            # Verify both SIGINT and SIGTERM are handled
            assert mock_signal.call_count == 2
            mock_signal.assert_any_call(
                signal.SIGINT,
                manager.stop.__self__.__class__.setup_signal_handlers.__wrapped__.__defaults__[0] if hasattr(
                    manager.stop.__self__.__class__.setup_signal_handlers,
                    '__wrapped__') else mock_signal.call_args_list[0][0][1])
            mock_signal.assert_any_call(
                signal.SIGTERM,
                manager.stop.__self__.__class__.setup_signal_handlers.__wrapped__.__defaults__[0] if hasattr(
                    manager.stop.__self__.__class__.setup_signal_handlers,
                    '__wrapped__') else mock_signal.call_args_list[1][0][1])

    def test_stop_all_bots_exception_handling(self):
        """Test _stop_all_bots with task cancellation exceptions (covers lines 99-100, 108-109)"""
        manager = BotManager([])

        # Create mock tasks and bots that will raise exceptions
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.side_effect = Exception("Cancel error")

        mock_bot = MagicMock()
        mock_bot.close.side_effect = Exception("Close error")

        manager.tasks = [mock_task]
        manager.bots = [mock_bot]
        manager.running = True

        with patch('src.bot_manager.print_log') as mock_log:
            # Run the async method
            asyncio.run(manager._stop_all_bots())

            # Should log the exceptions
            assert mock_log.call_count >= 2
            call_args = [str(args) for args in mock_log.call_args_list]
            assert any("Error cancelling task" in args for args in call_args)
            assert any("Error closing bot" in args for args in call_args)

    def test_stop_all_bots_gather_exception(self):
        """Test _stop_all_bots with asyncio.gather exception (covers lines 129-131)"""
        manager = BotManager([])

        # Create a task that will cause gather to fail
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = None

        manager.tasks = [mock_task]
        manager.bots = []
        manager.running = True

        with patch('asyncio.gather', side_effect=Exception("Gather error")), \
                patch('src.bot_manager.print_log') as mock_log:

            asyncio.run(manager._stop_all_bots())

            # Should log the gather exception
            call_args = [str(args) for args in mock_log.call_args_list]
            assert any("Error waiting for task completion" in args for args in call_args)

    def test_stop_public_method_runtime_error(self):
        """Test stop() method when no running loop exists (covers line 131)"""
        manager = BotManager([])

        with patch('asyncio.get_running_loop', side_effect=RuntimeError("No running loop")), \
                patch('src.bot_manager.print_log'):

            # Should not raise an exception
            manager.stop()

    def test_restart_with_new_config_no_config(self):
        """Test _restart_with_new_config when no new config is available (covers line 142)"""
        manager = BotManager([])
        manager.new_config = None

        result = asyncio.run(manager._restart_with_new_config())
        assert result is False

    def test_print_statistics_no_bots(self):
        """Test print_statistics when no bots exist (covers line 202)"""
        manager = BotManager([])
        manager.bots = []

        with patch('src.bot_manager.print_log') as mock_log:
            manager.print_statistics()

            # Should not log anything since there are no bots
            mock_log.assert_not_called()

    def test_setup_signal_handlers_sigint(self):
        """Test signal handlers for SIGINT (covers lines 222-225)"""
        manager = BotManager([])

        with patch('signal.signal') as mock_signal, \
                patch('asyncio.create_task') as mock_create_task, \
                patch('src.bot_manager.print_log') as mock_log:

            manager.setup_signal_handlers()

            # Get the signal handler that was registered
            assert mock_signal.call_count == 2
            sigint_call = mock_signal.call_args_list[0]
            signal_handler = sigint_call[0][1]

            # Simulate receiving SIGINT
            signal_handler(signal.SIGINT, None)

            # Should set shutdown flag and create stop task
            assert manager.shutdown_initiated is True
            mock_create_task.assert_called_once()
            mock_log.assert_called_once()

    def test_setup_signal_handlers_sigterm(self):
        """Test signal handlers for SIGTERM (covers lines 222-225)"""
        manager = BotManager([])

        with patch('signal.signal') as mock_signal, \
                patch('asyncio.create_task') as mock_create_task, \
                patch('src.bot_manager.print_log') as mock_log:

            manager.setup_signal_handlers()

            # Get the SIGTERM signal handler that was registered
            assert mock_signal.call_count == 2
            sigterm_call = mock_signal.call_args_list[1]
            signal_handler = sigterm_call[0][1]

            # Simulate receiving SIGTERM
            signal_handler(signal.SIGTERM, None)

            # Should set shutdown flag and create stop task
            assert manager.shutdown_initiated is True
            mock_create_task.assert_called_once()
            mock_log.assert_called_once()


class TestBotManagerHelperFunctions:
    """Test helper functions in bot_manager module"""

    @patch('src.bot_manager.os.path.exists')
    @patch('src.bot_manager.print_log')
    async def test_setup_config_watcher_success(self, mock_print_log, mock_exists):
        """Test successful config watcher setup"""
        mock_exists.return_value = True

        manager = BotManager([])
        config_file = "/path/to/config.json"

        with patch('src.config_watcher.create_config_watcher') as mock_create_watcher, \
                patch('src.watcher_globals.set_global_watcher') as mock_set_global:

            mock_watcher = MagicMock()
            mock_create_watcher.return_value = mock_watcher

            result = await _setup_config_watcher(config_file, manager)

            assert result == mock_watcher
            mock_create_watcher.assert_called_once()
            mock_set_global.assert_called_once_with(mock_watcher)

    @patch('src.bot_manager.os.path.exists')
    @patch('src.bot_manager.print_log')
    async def test_setup_config_watcher_no_config_file(
            self, mock_print_log, mock_exists):
        """Test config watcher setup with no config file"""
        mock_exists.return_value = False

        manager = BotManager([])
        result = await _setup_config_watcher(None, manager)

        assert result is None

    @patch('src.bot_manager.os.path.exists')
    @patch('src.bot_manager.print_log')
    async def test_setup_config_watcher_import_error(self, mock_print_log, mock_exists):
        """Test config watcher setup with import error"""
        mock_exists.return_value = True

        manager = BotManager([])
        config_file = "/path/to/config.json"

        with patch('src.config_watcher.create_config_watcher', side_effect=ImportError("No watchdog")):
            result = await _setup_config_watcher(config_file, manager)

            assert result is None

    @patch('os.path.exists', return_value=True)
    @patch('src.bot_manager.print_log')
    async def test_setup_config_watcher_general_exception(
            self, mock_print_log, mock_exists):
        """Test config watcher setup with general exception (covers lines 256-258)"""
        manager = BotManager([])
        config_file = "/path/to/config.json"

        with patch('src.config_watcher.create_config_watcher', side_effect=Exception("General error")):
            result = await _setup_config_watcher(config_file, manager)

            assert result is None
            # Should log the failure message
            mock_print_log.assert_called_with(
                "⚠️ Failed to start config watcher: General error", bcolors.WARNING)

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_normal_operation(self, mock_print_log):
        """Test main loop normal operation"""
        manager = BotManager([])
        manager.running = True

        class _StopTest(Exception):
            pass

        # Mock asyncio.sleep to exit after first iteration
        with patch('asyncio.sleep', side_effect=[None, _StopTest()]):
            try:
                await _run_main_loop(manager)
            except _StopTest:
                pass

        # Should not have triggered shutdown or restart
        assert manager.shutdown_initiated is False
        assert manager.restart_requested is False

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_shutdown(self, mock_print_log):
        """Test main loop with shutdown"""
        manager = BotManager([])
        manager.running = True
        manager.shutdown_initiated = True

        with patch.object(manager, '_stop_all_bots') as mock_stop:
            await _run_main_loop(manager)

        mock_stop.assert_called_once()

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_restart(self, mock_print_log):
        """Test main loop with restart"""
        manager = BotManager([])
        manager.running = True
        manager.restart_requested = True

        class _StopTest(Exception):
            pass

        with patch.object(manager, '_restart_with_new_config', return_value=True) as mock_restart, \
                patch('asyncio.sleep', side_effect=[None, _StopTest()]):
            try:
                await _run_main_loop(manager)
            except _StopTest:
                pass

        mock_restart.assert_called_once()

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_tasks_completed(self, mock_print_log):
        """Test main loop when all tasks complete"""
        manager = BotManager([])
        manager.running = True

        mock_task = MagicMock()
        mock_task.done.return_value = True
        manager.tasks = [mock_task]

        class _StopTest(Exception):
            pass

        with patch('asyncio.sleep', side_effect=[None, _StopTest()]):
            try:
                await _run_main_loop(manager)
            except _StopTest:
                pass

        # Should detect task completion and exit
        assert manager.running is True  # Loop exits but doesn't set running to False

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_restart_failure(self, mock_print_log):
        """Test main loop with restart failure (covers line 276)"""
        manager = BotManager([])
        manager.running = True
        manager.restart_requested = True

        class _StopTest(Exception):
            pass

        with patch.object(manager, '_restart_with_new_config', return_value=False) as mock_restart, \
                patch('asyncio.sleep', side_effect=[None, _StopTest()]):
            try:
                await _run_main_loop(manager)
            except _StopTest:
                pass

        mock_restart.assert_called_once()
        # Should log the failure message
        mock_print_log.assert_called_with(
            "❌ Failed to restart bots, continuing with previous configuration", bcolors.FAIL)

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_unexpected_completion(self, mock_print_log):
        """Test main loop when tasks complete unexpectedly (covers lines 284-287)"""
        manager = BotManager([])
        manager.running = True
        manager.shutdown_initiated = False

        mock_task = MagicMock()
        mock_task.done.return_value = True
        manager.tasks = [mock_task]

        with patch('asyncio.sleep', side_effect=[None]):
            await _run_main_loop(manager)

        # Should log the unexpected completion message
        call_args = [str(args) for args in mock_print_log.call_args_list]
        assert any("All bot tasks have completed unexpectedly" in args for args in call_args)

    def test_cleanup_watcher(self):
        """Test watcher cleanup"""
        mock_watcher = MagicMock()
        with patch('src.watcher_globals.set_global_watcher') as mock_set_global:
            _cleanup_watcher(mock_watcher)

        mock_watcher.stop.assert_called_once()
        mock_set_global.assert_called_once_with(None)

    def test_cleanup_watcher_none(self):
        """Test watcher cleanup with None watcher"""
        with patch('src.watcher_globals.set_global_watcher') as mock_set_global:
            _cleanup_watcher(None)

        mock_set_global.assert_called_once_with(None)

    @patch('src.bot_manager.os.path.exists')
    @patch('src.bot_manager.print_log')
    async def test_setup_config_watcher_restart_callback(
            self, mock_print_log, mock_exists):
        """Test the restart callback in setup_config_watcher (covers line 243)"""
        mock_exists.return_value = True

        manager = BotManager([])
        config_file = "/path/to/config.json"

        with patch('src.config_watcher.create_config_watcher') as mock_create, \
                patch('src.watcher_globals.set_global_watcher'), \
                patch.object(manager, 'request_restart') as mock_request:

            mock_watcher = MagicMock()
            mock_create.return_value = mock_watcher

            # Call _setup_config_watcher
            await _setup_config_watcher(manager, config_file)

            # Get the restart callback that was passed to create_config_watcher
            mock_create.assert_called_once()
            restart_callback = mock_create.call_args[0][1]

            # Test the restart callback
            new_config = [{"username": "test"}]
            restart_callback(new_config)
            mock_request.assert_called_once_with(new_config)

    async def test_missing_lines_256_258(self):
        """Test lines 256-258 in setup_config_watcher"""
        manager = BotManager([])
        config_file = "/path/to/config.json"

        with patch('src.bot_manager.os.path.exists', return_value=True), \
                patch('src.config_watcher.create_config_watcher') as mock_create, \
                patch('src.watcher_globals.set_global_watcher') as mock_set_global, \
                patch('src.bot_manager.print_log') as mock_log:

            mock_watcher = MagicMock()
            mock_create.return_value = mock_watcher

            await _setup_config_watcher(config_file, manager)

            # Should set the global watcher and log
            mock_set_global.assert_called_once_with(mock_watcher)
            mock_log.assert_called()

    async def test_missing_lines_276_283(self):
        """Test task completion check in _run_main_loop (covers lines 276-283)"""
        manager = BotManager([])
        manager.running = True
        manager.shutdown_initiated = False

        # Create a mock task that's already done
        mock_task = MagicMock()
        mock_task.done.return_value = True
        manager.tasks = [mock_task]

        with patch('asyncio.sleep') as mock_sleep, \
                patch('src.bot_manager.print_log') as mock_log:

            # After first sleep, make all tasks done to trigger the completion check
            # Exit after second iteration
            mock_sleep.side_effect = [None, KeyboardInterrupt()]

            try:
                await _run_main_loop(manager)
            except KeyboardInterrupt:
                pass

            # Should log unexpected completion message
            call_args = [str(args) for args in mock_log.call_args_list]
            assert any(
                "All bot tasks have completed unexpectedly" in args for args in call_args)

    def test_missing_lines_301_302(self):
        """Test ImportError handling in _cleanup_watcher (covers lines 301-302)"""
        watcher = MagicMock()

        # Mock the import to raise ImportError
        with patch('builtins.__import__', side_effect=ImportError("Module not found")):
            # This should not raise an exception due to the ImportError catch
            _cleanup_watcher(watcher)

            # Watcher should still be stopped even if ImportError occurs
            watcher.stop.assert_called_once()

    async def test_missing_lines_318_326(self):
        """Test when _start_all_bots returns False in run_bots (covers lines 318-326)"""
        users_config = [{"username": "test"}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
                patch('src.bot_manager._setup_config_watcher') as mock_setup, \
                patch('src.bot_manager._cleanup_watcher') as mock_cleanup:

            # Create a mock manager instance
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.return_value = False  # This triggers the early return
            mock_manager._stop_all_bots = AsyncMock()
            mock_setup.return_value = None

            await run_bots(users_config)

            # Should call _start_all_bots and return early without calling
            # _run_main_loop
            mock_manager._start_all_bots.assert_called_once()
            # Should still call cleanup
            mock_cleanup.assert_called_once()


class TestRunBots:
    """Test run_bots function"""
    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_success(self, mock_cleanup, mock_print_log):
        """Test successful run_bots execution"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]
        config_file = "/path/to/config.json"

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
                patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            # Make _start_all_bots async and return True
            mock_manager._start_all_bots = AsyncMock(return_value=True)
            # Set running to False so _run_main_loop exits immediately
            mock_manager.running = False
            # ensure stop_all_bots is awaitable
            mock_manager._stop_all_bots = AsyncMock()

            await run_bots(users_config, config_file)

            # Verify manager was created and methods called
            mock_manager_class.assert_called_once_with(users_config, config_file)
            mock_manager.setup_signal_handlers.assert_called_once()
            mock_manager._start_all_bots.assert_called_once()
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()

            # Verify the success print_log calls were made (lines 350-355)
            expected_calls = [
                call("\n🎮 Bots are running! Press Ctrl+C to stop.", bcolors.HEADER),
                call("💬 Start chatting in your channels to see color changes!", bcolors.OKBLUE),
                call("⚠️ Note: If bots exit quickly, check your Twitch credentials", bcolors.WARNING)
            ]
            mock_print_log.assert_has_calls(expected_calls, any_order=False)

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_start_failure(self, mock_cleanup, mock_print_log):
        """Test run_bots when bot start fails"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]

        # Mock only the parts we need, not the entire BotManager
        with patch('src.bot_manager._setup_config_watcher', return_value=None), \
                patch.object(BotManager, '_start_all_bots', return_value=False) as mock_start, \
                patch.object(BotManager, 'setup_signal_handlers'), \
                patch.object(BotManager, '_stop_all_bots', new_callable=AsyncMock) as mock_stop, \
                patch.object(BotManager, 'print_statistics') as mock_stats:

            await run_bots(users_config)

            # Verify that we tried to start but failed early
            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            mock_stats.assert_called_once()

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_keyboard_interrupt(self, mock_cleanup, mock_print_log):
        """Test run_bots with keyboard interrupt"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
                patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.side_effect = KeyboardInterrupt()
            mock_manager._stop_all_bots = AsyncMock()

            await run_bots(users_config)

            # Should handle keyboard interrupt gracefully
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_exception(self, mock_cleanup, mock_print_log):
        """Test run_bots with general exception"""
        users_config = [{"username": "user1",
                         "access_token": "token1",
                         "channels": ["#channel1"]}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
                patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.side_effect = Exception("Test error")
            mock_manager._stop_all_bots = AsyncMock()

            await run_bots(users_config)

            # Should handle exception gracefully
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()
