"""
Logging configuration module for Twitch Color Changer Bot.

Provides a clean, configurable logging setup using colorlog library.
"""

import logging
import os
import sys

import colorlog


class FseventsFilter(logging.Filter):
    """Filter to suppress fsevents-related log messages."""

    def filter(self, record):
        """Return False to suppress the log record if it contains 'fsevents'."""
        return "fsevents" not in record.getMessage().lower()


class LoggerConfigurator:
    """Handles logging configuration cleanly using colorlog.

    Supports environment variable configuration for log levels.
    """

    def __init__(self, config=None):
        """Initialize the configurator.

        Args:
            config: Optional config dict for future extensibility.
        """
        self.config = config or {}

    def configure(self):
        """Configure logging with colored output using colorlog.

        Uses environment variables:
        - DEBUG: Set to 'true', '1', or 'yes' for DEBUG level, otherwise INFO
        """
        # Determine log level from environment
        debug_env = os.environ.get("DEBUG", "").lower()
        log_level = logging.DEBUG if debug_env in ("true", "1", "yes") else logging.INFO

        # Create formatter with matching colors and secondary log colors
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(levelname)-8s%(reset)s %(message_log_color)s%(message)s",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "magenta",
            },
            secondary_log_colors={
                "message": {
                    "ERROR": "red",
                    "CRITICAL": "magenta",
                }
            },
            reset=True,
        )

        # Create handler
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
