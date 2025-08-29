"""
Tests for bot_manager.py module
"""

import pytest
import asyncio
import signal
import os
from unittest.mock import patch, AsyncMock, MagicMock, call
from src.bot_manager import BotManager, run_bots, _setup_config_watcher, _run_main_loop, _cleanup_watcher


class TestBotManager:
    """Test BotManager class"""

    def test_init(self):
        """Test BotManager initialization"""
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]
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
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]

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
        user_config = {"username": "testuser", "access_token": "token", "channels": ["#channel"]}

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
        new_config = [{"username": "newuser", "access_token": "newtoken", "channels": ["#newchannel"]}]

        manager.request_restart(new_config)

        assert manager.restart_requested is True
        assert manager.new_config == new_config

    @patch('src.bot_manager.print_log')
    async def test_restart_with_new_config(self, mock_print_log):
        """Test restarting with new configuration"""
        old_config = [{"username": "olduser", "access_token": "oldtoken", "channels": ["#oldchannel"]}]
        new_config = [{"username": "newuser", "access_token": "newtoken", "channels": ["#newchannel"]}]

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
            mock_signal.assert_any_call(signal.SIGINT, manager.stop.__self__.__class__.setup_signal_handlers.__wrapped__.__defaults__[0] if hasattr(manager.stop.__self__.__class__.setup_signal_handlers, '__wrapped__') else mock_signal.call_args_list[0][0][1])
            mock_signal.assert_any_call(signal.SIGTERM, manager.stop.__self__.__class__.setup_signal_handlers.__wrapped__.__defaults__[0] if hasattr(manager.stop.__self__.__class__.setup_signal_handlers, '__wrapped__') else mock_signal.call_args_list[1][0][1])


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
    async def test_setup_config_watcher_no_config_file(self, mock_print_log, mock_exists):
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

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_normal_operation(self, mock_print_log):
        """Test main loop normal operation"""
        manager = BotManager([])
        manager.running = True

        # Mock asyncio.sleep to exit after first iteration
        with patch('asyncio.sleep', side_effect=[None, KeyboardInterrupt()]):
            await _run_main_loop(manager)

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

        with patch.object(manager, '_restart_with_new_config', return_value=True) as mock_restart, \
             patch('asyncio.sleep', side_effect=[None, KeyboardInterrupt()]):
            await _run_main_loop(manager)

        mock_restart.assert_called_once()

    @patch('src.bot_manager.print_log')
    async def test_run_main_loop_tasks_completed(self, mock_print_log):
        """Test main loop when all tasks complete"""
        manager = BotManager([])
        manager.running = True

        mock_task = MagicMock()
        mock_task.done.return_value = True
        manager.tasks = [mock_task]

        with patch('asyncio.sleep', side_effect=[None, KeyboardInterrupt()]):
            await _run_main_loop(manager)

        # Should detect task completion and exit
        assert manager.running is True  # Loop exits but doesn't set running to False

    def test_cleanup_watcher(self):
        """Test watcher cleanup"""
        mock_watcher = MagicMock()

        with patch('src.bot_manager.set_global_watcher') as mock_set_global:
            _cleanup_watcher(mock_watcher)

        mock_watcher.stop.assert_called_once()
        mock_set_global.assert_called_once_with(None)

    def test_cleanup_watcher_none(self):
        """Test watcher cleanup with None watcher"""
        with patch('src.bot_manager.set_global_watcher') as mock_set_global:
            _cleanup_watcher(None)

        mock_set_global.assert_called_once_with(None)


class TestRunBots:
    """Test run_bots function"""

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_success(self, mock_cleanup, mock_print_log):
        """Test successful run_bots execution"""
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]
        config_file = "/path/to/config.json"

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
             patch('src.bot_manager._setup_config_watcher', return_value=None), \
             patch('src.bot_manager._run_main_loop'):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.return_value = True

            await run_bots(users_config, config_file)

            # Verify manager was created and methods called
            mock_manager_class.assert_called_once_with(users_config, config_file)
            mock_manager.setup_signal_handlers.assert_called_once()
            mock_manager._start_all_bots.assert_called_once()
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_start_failure(self, mock_cleanup, mock_print_log):
        """Test run_bots when bot start fails"""
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
             patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.return_value = False

            await run_bots(users_config)

            # Should not proceed to main loop when start fails
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_keyboard_interrupt(self, mock_cleanup, mock_print_log):
        """Test run_bots with keyboard interrupt"""
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
             patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.side_effect = KeyboardInterrupt()

            await run_bots(users_config)

            # Should handle keyboard interrupt gracefully
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()

    @patch('src.bot_manager.print_log')
    @patch('src.bot_manager._cleanup_watcher')
    async def test_run_bots_exception(self, mock_cleanup, mock_print_log):
        """Test run_bots with general exception"""
        users_config = [{"username": "user1", "access_token": "token1", "channels": ["#channel1"]}]

        with patch('src.bot_manager.BotManager') as mock_manager_class, \
             patch('src.bot_manager._setup_config_watcher', return_value=None):

            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            mock_manager._start_all_bots.side_effect = Exception("Test error")

            await run_bots(users_config)

            # Should handle exception gracefully
            mock_manager._stop_all_bots.assert_called_once()
            mock_manager.print_statistics.assert_called_once()
