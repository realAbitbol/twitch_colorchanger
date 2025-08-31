"""
Tests for config_watcher.py module
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from src.config_watcher import (
    ConfigFileHandler,
    ConfigWatcher,
    create_config_watcher,
    start_config_watcher,
)


class TestConfigFileHandler:
    """Test ConfigFileHandler class"""

    def test_init(self):
        """Test ConfigFileHandler initialization"""
        mock_watcher = MagicMock()
        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        assert handler.config_file == os.path.abspath("/path/to/config.json")
        assert handler.watcher == mock_watcher
        assert handler.last_modified == 0

    def test_on_modified_directory_ignored(self):
        """Test that directory events are ignored"""
        mock_watcher = MagicMock()
        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        mock_event = MagicMock()
        mock_event.is_directory = True
        mock_event.src_path = "/path/to/config.json"

        handler.on_modified(mock_event)

        # Should not call any watcher methods
        mock_watcher._on_config_changed.assert_not_called()

    def test_on_modified_different_file_ignored(self):
        """Test that events for different files are ignored"""
        mock_watcher = MagicMock()
        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/other.json"

        handler.on_modified(mock_event)

        mock_watcher._on_config_changed.assert_not_called()

    def test_on_modified_paused_ignored(self):
        """Test that events are ignored when watcher is paused"""
        mock_watcher = MagicMock()
        mock_watcher.paused = True
        mock_watcher._pause_lock = MagicMock()
        mock_watcher._pause_lock.__enter__ = MagicMock(return_value=None)
        mock_watcher._pause_lock.__exit__ = MagicMock(return_value=None)

        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/config.json"

        with patch("src.config_watcher.logger") as mock_logger:
            handler.on_modified(mock_event)

            mock_logger.debug.assert_called_with(
                "📝 Config change ignored (bot-initiated)"
            )
            mock_watcher._on_config_changed.assert_not_called()

    def test_on_modified_debounced(self):
        """Test that rapid events are debounced"""
        mock_watcher = MagicMock()
        mock_watcher.paused = False
        mock_watcher._pause_lock = MagicMock()
        mock_watcher._pause_lock.__enter__ = MagicMock(return_value=None)
        mock_watcher._pause_lock.__exit__ = MagicMock(return_value=None)

        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/config.json"

        # First call
        handler.on_modified(mock_event)

        # Second call immediately after (should be debounced)
        handler.on_modified(mock_event)

        # Should only trigger once due to debouncing
        assert mock_watcher._on_config_changed.call_count == 1

    @patch("src.config_watcher.threading.Thread")
    @patch("src.config_watcher.logger")
    def test_on_modified_success(self, mock_logger, mock_thread):
        """Test successful config file modification handling"""
        mock_watcher = MagicMock()
        mock_watcher.paused = False
        mock_watcher._pause_lock = MagicMock()
        mock_watcher._pause_lock.__enter__ = MagicMock(return_value=None)
        mock_watcher._pause_lock.__exit__ = MagicMock(return_value=None)

        handler = ConfigFileHandler("/path/to/config.json", mock_watcher)

        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/config.json"

        handler.on_modified(mock_event)

        mock_logger.info.assert_called_with(
            "📁 Config file changed: /path/to/config.json"
        )
        mock_thread.assert_called_once()
        _, kwargs = mock_thread.call_args
        assert kwargs["target"] == mock_watcher._on_config_changed
        assert kwargs["daemon"] is True


class TestConfigWatcher:
    """Test ConfigWatcher class"""

    def test_init(self):
        """Test ConfigWatcher initialization"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        assert watcher.config_file == "/path/to/config.json"
        assert watcher.restart_callback == mock_callback
        assert watcher.observer is None
        assert watcher.running is False
        assert watcher.paused is False

    @patch("src.config_watcher.logger")
    def test_pause_watching(self, mock_logger):
        """Test pausing the config watcher"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        watcher.pause_watching()

        assert watcher.paused is True
        mock_logger.debug.assert_called_with(
            "⏸️ Config watcher paused (bot update in progress)"
        )

    @patch("src.config_watcher.logger")
    def test_resume_watching(self, mock_logger):
        """Test resuming the config watcher"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)
        watcher.paused = True

        watcher.resume_watching()

        assert watcher.paused is False
        mock_logger.debug.assert_called_with("▶️ Config watcher resumed")

    def test_start_already_running(self):
        """Test starting when already running does nothing"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)
        watcher.running = True

        watcher.start()

        # Should not create observer or change state
        assert watcher.observer is None

    @patch("src.config_watcher.os.path.exists")
    @patch("src.config_watcher.logger")
    def test_start_config_dir_not_exists(self, mock_logger, mock_exists):
        """Test starting when config directory doesn't exist"""
        mock_exists.return_value = False
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        watcher.start()

        mock_logger.warning.assert_called_with(
            "Config directory does not exist: /path/to"
        )
        assert watcher.running is False

    @patch("src.config_watcher.os.path.exists")
    @patch("src.config_watcher.Observer")
    @patch("src.config_watcher.logger")
    def test_start_success(self, mock_logger, mock_observer_class, mock_exists):
        """Test successful watcher start"""
        mock_exists.return_value = True
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_observer = MagicMock()
        mock_observer_class.return_value = mock_observer

        watcher.start()

        assert watcher.running is True
        assert watcher.observer == mock_observer
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()
        mock_logger.info.assert_called_with(
            "👀 Started watching config file: /path/to/config.json"
        )

    @patch("src.config_watcher.os.path.exists")
    @patch("src.config_watcher.Observer")
    @patch("src.config_watcher.logger")
    def test_start_exception(self, mock_logger, mock_observer_class, mock_exists):
        """Test watcher start with exception"""
        mock_exists.return_value = True
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_observer = MagicMock()
        mock_observer.schedule.side_effect = Exception("Test error")
        mock_observer_class.return_value = mock_observer

        watcher.start()

        assert watcher.running is False
        mock_logger.error.assert_called_with(
            "Failed to start config watcher: Test error"
        )

    @patch("src.config_watcher.logger")
    def test_stop_not_running(self, mock_logger):
        """Test stopping when not running"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        watcher.stop()

        # Should not call any observer methods
        mock_logger.info.assert_not_called()

    @patch("src.config_watcher.logger")
    def test_stop_success(self, mock_logger):
        """Test successful watcher stop"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_observer = MagicMock()
        watcher.observer = mock_observer
        watcher.running = True

        watcher.stop()

        assert watcher.running is False
        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()
        mock_logger.info.assert_called_with("👁️ Stopped config file watcher")

    @patch("src.config_watcher.load_users_from_config")
    @patch("src.config_watcher.get_valid_users")
    @patch("src.config_watcher.logger")
    def test_on_config_changed_empty_config(
        self, mock_logger, mock_get_valid, mock_load
    ):
        """Test config change with empty config"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_load.return_value = None

        watcher._on_config_changed()

        mock_logger.warning.assert_called_with(
            "⚠️ Config file is empty or invalid, ignoring changes"
        )
        mock_callback.assert_not_called()

    @patch("src.config_watcher.load_users_from_config")
    @patch("src.config_watcher.get_valid_users")
    @patch("src.config_watcher.logger")
    def test_on_config_changed_no_valid_users(
        self, mock_logger, mock_get_valid, mock_load
    ):
        """Test config change with no valid users"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_load.return_value = {"user1": {}}
        mock_get_valid.return_value = []

        watcher._on_config_changed()

        mock_logger.error.assert_called_with(
            "❌ New config contains no valid users, ignoring changes"
        )
        mock_callback.assert_not_called()

    @patch("src.config_watcher.load_users_from_config")
    @patch("src.config_watcher.get_valid_users")
    @patch("src.config_watcher.logger")
    def test_on_config_changed_success(self, mock_logger, mock_get_valid, mock_load):
        """Test successful config change handling"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_load.return_value = {"user1": {}, "user2": {}}
        mock_get_valid.return_value = [{"name": "user1"}, {"name": "user2"}]

        watcher._on_config_changed()

        mock_logger.info.assert_called_with(
            "✅ Config validation passed - 2 valid user(s)"
        )
        mock_callback.assert_called_once_with([{"name": "user1"}, {"name": "user2"}])

    @patch("src.config_watcher.load_users_from_config")
    @patch("src.config_watcher.logger")
    def test_on_config_changed_exception(self, mock_logger, mock_load):
        """Test config change with exception"""
        mock_callback = MagicMock()
        watcher = ConfigWatcher("/path/to/config.json", mock_callback)

        mock_load.side_effect = Exception("Test error")

        watcher._on_config_changed()

        mock_logger.error.assert_called_with(
            "Error processing config change: Test error"
        )
        mock_callback.assert_not_called()


class TestConfigWatcherFunctions:
    """Test standalone functions in config_watcher module"""

    @patch("src.config_watcher.ConfigWatcher")
    def test_start_config_watcher(self, mock_watcher_class):
        """Test start_config_watcher function"""
        mock_callback = MagicMock()
        mock_watcher = MagicMock()
        mock_watcher_class.return_value = mock_watcher

        result = start_config_watcher("/path/to/config.json", mock_callback)

        assert result == mock_watcher
        mock_watcher.start.assert_called_once()

    @patch("src.config_watcher.ConfigWatcher")
    @patch("src.config_watcher.asyncio.get_event_loop")
    async def test_create_config_watcher(self, mock_get_loop, mock_watcher_class):
        """Test create_config_watcher function"""
        mock_callback = MagicMock()
        mock_watcher = MagicMock()
        mock_watcher_class.return_value = mock_watcher

        mock_loop = MagicMock()
        # run_in_executor is used via await loop.run_in_executor(...)
        mock_loop.run_in_executor = AsyncMock()
        mock_get_loop.return_value = mock_loop

        result = await create_config_watcher("/path/to/config.json", mock_callback)

        assert result == mock_watcher
        mock_loop.run_in_executor.assert_called_once()
