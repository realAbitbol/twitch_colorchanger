"""
Tests for watcher_globals.py module
"""

import pytest
from unittest.mock import MagicMock, patch
from src.watcher_globals import set_global_watcher, pause_config_watcher, resume_config_watcher


class TestWatcherGlobals:
    """Test watcher_globals module functions"""

    def test_set_global_watcher(self):
        """Test setting the global watcher instance"""
        mock_watcher = MagicMock()
        set_global_watcher(mock_watcher)

        # Test that pause_config_watcher uses the set watcher
        pause_config_watcher()
        mock_watcher.pause_watching.assert_called_once()

    def test_pause_config_watcher_no_watcher(self):
        """Test pausing when no global watcher is set"""
        # Reset global watcher
        set_global_watcher(None)

        # Should not raise any errors
        pause_config_watcher()

    def test_resume_config_watcher_no_watcher(self):
        """Test resuming when no global watcher is set"""
        # Reset global watcher
        set_global_watcher(None)

        # Should not raise any errors
        resume_config_watcher()

    def test_pause_config_watcher_with_watcher(self):
        """Test pausing with a valid global watcher"""
        mock_watcher = MagicMock()
        set_global_watcher(mock_watcher)

        pause_config_watcher()

        mock_watcher.pause_watching.assert_called_once()

    def test_resume_config_watcher_with_watcher(self):
        """Test resuming with a valid global watcher"""
        mock_watcher = MagicMock()
        set_global_watcher(mock_watcher)

        resume_config_watcher()

        mock_watcher.resume_watching.assert_called_once()

    def test_multiple_set_global_watcher(self):
        """Test setting multiple global watchers (last one wins)"""
        mock_watcher1 = MagicMock()
        mock_watcher2 = MagicMock()

        set_global_watcher(mock_watcher1)
        set_global_watcher(mock_watcher2)

        pause_config_watcher()

        # Only the second watcher should be called
        mock_watcher1.pause_watching.assert_not_called()
        mock_watcher2.pause_watching.assert_called_once()

    def test_watcher_methods_called_correctly(self):
        """Test that the correct watcher methods are called"""
        mock_watcher = MagicMock()
        set_global_watcher(mock_watcher)

        # Test pause
        pause_config_watcher()
        mock_watcher.pause_watching.assert_called_once()
        mock_watcher.resume_watching.assert_not_called()

        # Reset mock
        mock_watcher.reset_mock()

        # Test resume
        resume_config_watcher()
        mock_watcher.pause_watching.assert_not_called()
        mock_watcher.resume_watching.assert_called_once()
