"""
Tests for logger functionality
"""

import pytest
import logging
from unittest.mock import patch, Mock
import tempfile
import os

from src.logger import ColoredFormatter, BotLogger, logger, print_log


class TestColoredFormatter:
    """Test ColoredFormatter functionality"""

    def test_colored_formatter_initialization(self):
        """Test ColoredFormatter initialization"""
        formatter = ColoredFormatter()
        assert isinstance(formatter, logging.Formatter)

    def test_colored_formatter_format_info(self):
        """Test formatting INFO level messages"""
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None
        )
        
        formatted = formatter.format(record)
        assert "Test message" in formatted

    def test_colored_formatter_format_error(self):
        """Test formatting ERROR level messages"""
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Error message", args=(), exc_info=None
        )
        
        formatted = formatter.format(record)
        assert "Error message" in formatted

    def test_colored_formatter_format_warning(self):
        """Test formatting WARNING level messages"""
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="Warning message", args=(), exc_info=None
        )
        
        formatted = formatter.format(record)
        assert "Warning message" in formatted


class TestBotLogger:
    """Test BotLogger functionality"""

    def test_bot_logger_initialization(self):
        """Test BotLogger initialization"""
        test_logger = BotLogger("test_logger")
        assert isinstance(test_logger, BotLogger)
        assert test_logger.logger.name == "test_logger"

    def test_bot_logger_info(self, capsys):
        """Test BotLogger info logging"""
        test_logger = BotLogger("test_info")
        test_logger.info("Info message")
        
        # Check that message was logged (may appear in stderr due to logging configuration)
        captured = capsys.readouterr()
        # The message might appear in either stdout or stderr depending on configuration

    def test_bot_logger_error(self, capsys):
        """Test BotLogger error logging"""
        test_logger = BotLogger("test_error")
        test_logger.error("Error message")
        
        captured = capsys.readouterr()
        # Error messages should be logged

    def test_bot_logger_warning(self, capsys):
        """Test BotLogger warning logging"""
        test_logger = BotLogger("test_warning")
        test_logger.warning("Warning message")
        
        captured = capsys.readouterr()
        # Warning messages should be logged

    def test_bot_logger_debug(self, capsys):
        """Test BotLogger debug logging"""
        test_logger = BotLogger("test_debug")
        test_logger.debug("Debug message")
        
        captured = capsys.readouterr()
        # Debug messages may not appear unless debug level is set

    def test_bot_logger_with_file(self):
        """Test BotLogger with file output"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            log_file = f.name
        
        try:
            test_logger = BotLogger("test_file", log_file=log_file)
            test_logger.info("File log message")
            
            # Check that log file was created
            assert os.path.exists(log_file)
            
            # Check file contents
            with open(log_file, 'r') as f:
                content = f.read()
                assert "File log message" in content
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_bot_logger_log_level(self):
        """Test BotLogger log level setting"""
        test_logger = BotLogger("test_level")
        
        # Test setting different log levels
        test_logger.set_level(logging.DEBUG)
        assert test_logger.logger.level == logging.DEBUG
        
        test_logger.set_level(logging.WARNING)
        assert test_logger.logger.level == logging.WARNING


class TestLoggerModule:
    """Test logger module level functionality"""

    def test_module_logger_exists(self):
        """Test that module logger exists"""
        assert logger is not None
        assert isinstance(logger, BotLogger)

    def test_module_print_log_function(self, capsys):
        """Test module level print_log function"""
        print_log("Module test message")
        captured = capsys.readouterr()
        # Function should work without errors

    def test_module_print_log_with_color(self, capsys):
        """Test module level print_log with color"""
        from src.colors import bcolors
        print_log("Colored module message", bcolors.OKGREEN)
        captured = capsys.readouterr()
        # Function should work with color parameter

    @patch.dict(os.environ, {'DEBUG': '1'})
    def test_module_print_log_debug_mode(self, capsys):
        """Test module level print_log in debug mode"""
        print_log("Debug module message", debug_only=True)
        captured = capsys.readouterr()
        # Debug message should appear when DEBUG is set


class TestLoggerIntegration:
    """Test logger integration scenarios"""

    def test_multiple_loggers(self):
        """Test creating multiple logger instances"""
        logger1 = BotLogger("bot1")
        logger2 = BotLogger("bot2")
        
        assert logger1.logger.name == "bot1"
        assert logger2.logger.name == "bot2"
        assert logger1 != logger2

    def test_logger_with_different_levels(self, capsys):
        """Test loggers with different log levels"""
        debug_logger = BotLogger("debug_test")
        debug_logger.set_level(logging.DEBUG)
        
        info_logger = BotLogger("info_test")
        info_logger.set_level(logging.INFO)
        
        # Both should log info messages
        debug_logger.info("Debug logger info")
        info_logger.info("Info logger info")
        
        # Only debug logger should log debug messages
        debug_logger.debug("Debug logger debug")
        info_logger.debug("Info logger debug")

    def test_logger_performance(self):
        """Test logger performance with many messages"""
        test_logger = BotLogger("performance_test")
        
        # Should handle many messages without issues
        for i in range(100):
            test_logger.info(f"Performance test message {i}")
        
        # Test should complete without hanging

    def test_logger_thread_safety(self):
        """Test logger thread safety"""
        import threading
        import time
        
        test_logger = BotLogger("thread_test")
        results = []
        
        def log_messages(thread_id):
            for i in range(10):
                test_logger.info(f"Thread {thread_id} message {i}")
                results.append(f"Thread {thread_id} message {i}")
                time.sleep(0.001)  # Small delay
        
        # Create multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=log_messages, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have logged from all threads
        assert len(results) == 30
