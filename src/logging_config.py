"""
Logging configuration module for Twitch Color Changer Bot.

Provides a clean, configurable logging setup without monkey-patching.
"""

import logging
import os
import sys


class ColoredFormatter(logging.Formatter):
    """Custom logging formatter that adds ANSI color codes to log levels.

    This formatter enhances log output by coloring log level names using
    ANSI escape sequences, making it easier to distinguish different log
    levels in terminal output.

    Attributes:
        COLORS: Dictionary mapping log level names to ANSI color codes.
        RESET: ANSI code to reset text formatting.
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        """Format the log record with colored level names.

        Applies color coding to the log level and formats the message
        without including the logger name for cleaner output.

        Args:
            record: The LogRecord instance to format.

        Returns:
            The formatted log message string with colored level.
        """
        # Get the colored level name with fixed width alignment
        level_name = record.levelname
        colored_level = f"{self.COLORS.get(level_name, '')}{level_name:<8}{self.RESET}"

        # Format the message without logger name
        message = record.getMessage()

        # Return formatted string with level and message
        return f"{colored_level} {message}"


class FseventsFilter(logging.Filter):
    """Filter to suppress fsevents-related log messages."""

    def filter(self, record):
        """Return False to suppress the log record if it contains 'fsevents'."""
        return "fsevents" not in record.getMessage().lower()


class LoggerConfigurator:
    """Handles logging configuration cleanly without monkey-patching.

    Supports environment variable configuration for log levels.
    """

    def __init__(self, config=None):
        """Initialize the configurator.

        Args:
            config: Optional config dict for future extensibility.
        """
        self.config = config or {}

    def configure(self):
        """Configure logging with colored output.

        Uses environment variables:
        - DEBUG: Set to 'true', '1', or 'yes' for DEBUG level, otherwise INFO
        """
        # Determine log level from environment
        debug_env = os.environ.get("DEBUG", "").lower()
        log_level = logging.DEBUG if debug_env in ("true", "1", "yes") else logging.INFO

        # Create formatter and handler
        formatter = ColoredFormatter("%(message)s")
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        handler.addFilter(FseventsFilter())

        # Configure root logger
        logging.basicConfig(
            level=log_level,
            handlers=[handler],
            format="%(message)s",
        )

        # Ensure root logger level is set
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # Apply formatter and filter to all existing handlers (in case any were added)
        for h in root_logger.handlers:
            h.setFormatter(formatter)
            h.addFilter(FseventsFilter())
