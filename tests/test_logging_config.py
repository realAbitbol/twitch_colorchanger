"""Tests for logging_config.py module."""

import logging

import colorlog
import pytest

from src.logging_config import FseventsFilter, LoggerConfigurator


class TestColoredFormatter:
    """Tests for colorlog.ColoredFormatter color codes and level names."""

    @pytest.fixture
    def formatter(self):
        """Return a colorlog.ColoredFormatter instance."""
        return colorlog.ColoredFormatter(
            "%(log_color)s%(levelname)-8s%(reset)s %(message)s",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "magenta",
            },
        )

    def test_colored_formatter_debug_color(self, formatter):
        """Test DEBUG level color code."""
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="", lineno=0, msg="test", args=(), exc_info=None
        )
        formatted = formatter.format(record)
        # colorlog uses different ANSI codes, so we check for cyan color and DEBUG text
        assert "\033[36m" in formatted  # Cyan color code
        assert "DEBUG" in formatted
        assert "test" in formatted

    def test_colored_formatter_info_color(self, formatter):
        """Test INFO level color code."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="test", args=(), exc_info=None
        )
        formatted = formatter.format(record)
        # Check for green color and INFO text
        assert "\033[32m" in formatted  # Green color code
        assert "INFO" in formatted
        assert "test" in formatted

    def test_colored_formatter_warning_color(self, formatter):
        """Test WARNING level color code."""
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0, msg="test", args=(), exc_info=None
        )
        formatted = formatter.format(record)
        # Check for yellow color and WARNING text
        assert "\033[33m" in formatted  # Yellow color code
        assert "WARNING" in formatted
        assert "test" in formatted

    def test_colored_formatter_error_color(self, formatter):
        """Test ERROR level color code."""
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0, msg="test", args=(), exc_info=None
        )
        formatted = formatter.format(record)
        # Check for red color and ERROR text
        assert "\033[31m" in formatted  # Red color code
        assert "ERROR" in formatted
        assert "test" in formatted


class TestFseventsFilter:
    """Tests for FseventsFilter message filtering."""

    @pytest.fixture
    def filter_instance(self):
        """Return a FseventsFilter instance."""
        return FseventsFilter()

    def test_fsevents_filter_blocks_fsevents(self, filter_instance):
        """Test that messages containing 'fsevents' are filtered out."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="fsevents detected", args=(), exc_info=None
        )
        assert not filter_instance.filter(record)

    def test_fsevents_filter_allows_other(self, filter_instance):
        """Test that messages not containing 'fsevents' are allowed."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="normal message", args=(), exc_info=None
        )
        assert filter_instance.filter(record)


class TestLoggerConfigurator:
    """Tests for LoggerConfigurator env parsing and handler setup."""

    @pytest.fixture
    def configurator(self):
        """Return a LoggerConfigurator instance."""
        return LoggerConfigurator()

    def test_logger_configurator_debug_env_true(self, configurator, monkeypatch):
        """Test DEBUG env parsing when set to true."""
        monkeypatch.setenv("DEBUG", "true")
        configurator.configure()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_logger_configurator_debug_env_false(self, configurator, monkeypatch):
        """Test DEBUG env parsing when set to false."""
        monkeypatch.setenv("DEBUG", "false")
        configurator.configure()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_logger_configurator_handler_setup(self, configurator):
        """Test that handler is set up with formatter and filter."""
        configurator.configure()
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) >= 1
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, colorlog.ColoredFormatter)
        assert any(isinstance(f, FseventsFilter) for f in handler.filters)

    def test_logger_configurator_configure_integration(self, configurator, monkeypatch):
        """Integration test for configure method."""
        monkeypatch.setenv("DEBUG", "1")
        configurator.configure()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
        assert len(root_logger.handlers) >= 1
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, colorlog.ColoredFormatter)
        assert any(isinstance(f, FseventsFilter) for f in handler.filters)
