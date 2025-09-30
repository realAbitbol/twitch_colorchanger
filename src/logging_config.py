r"""
Logging configuration module for Twitch Color Changer Bot.

Provides a clean, configurable logging setup using colorlog library with
structured error logging and aggregation capabilities.
"""

import atexit
import logging
import os
import sys
import threading
import time
from collections import defaultdict
from typing import Any

import colorlog


class FseventsFilter(logging.Filter):
    """Filter to suppress fsevents-related log messages."""

    def filter(self, record):
        """Return False to suppress the log record if it contains 'fsevents'."""
        return "fsevents" not in record.getMessage().lower()


class ErrorAggregator:
    """Aggregates and reports error patterns for monitoring and alerting.

    Tracks error frequencies, provides summary reports, and can trigger
    alerts for critical error patterns in long-running operations.
    """

    def __init__(self):
        self.errors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.lock = threading.Lock()
        self.start_time = time.time()

    def record_error(self, error_type: str, message: str, context: dict[str, Any] = None) -> None:
        """Record an error occurrence with context."""
        with self.lock:
            error_entry = {
                "timestamp": time.time(),
                "message": message,
                "context": context or {},
            }
            self.errors[error_type].append(error_entry)

            # Keep only recent errors (last 1000 per type)
            if len(self.errors[error_type]) > 1000:
                self.errors[error_type] = self.errors[error_type][-1000:]

    def get_error_summary(self) -> dict[str, Any]:
        """Get a summary of error patterns."""
        with self.lock:
            summary = {}
            current_time = time.time()
            runtime_hours = (current_time - self.start_time) / 3600

            for error_type, occurrences in self.errors.items():
                recent_count = len([e for e in occurrences if current_time - e["timestamp"] < 3600])  # last hour
                total_count = len(occurrences)
                rate_per_hour = total_count / max(runtime_hours, 1)

                summary[error_type] = {
                    "total_count": total_count,
                    "recent_count": recent_count,
                    "rate_per_hour": rate_per_hour,
                    "last_occurrence": occurrences[-1] if occurrences else None,
                }

            return summary

    def should_alert(self, error_type: str, threshold_rate: float = 10.0) -> bool:
        """Check if an error type should trigger an alert based on rate."""
        summary = self.get_error_summary()
        if error_type not in summary:
            return False
        return summary[error_type]["rate_per_hour"] > threshold_rate

    def log_summary_report(self) -> None:
        """Log a summary report of error patterns."""
        summary = self.get_error_summary()
        if not summary:
            logging.info("No errors recorded in current session")
            return

        logging.warning("🚨 ERROR SUMMARY REPORT")
        for error_type, stats in summary.items():
            logging.warning(
                f"  {error_type}: {stats['total_count']} total, "
                f"{stats['recent_count']} in last hour, "
                f"{stats['rate_per_hour']:.1f}/hour"
            )
            if stats["last_occurrence"]:
                logging.warning(f"    Last: {stats['last_occurrence']['message']}")


# Global error aggregator instance
error_aggregator = ErrorAggregator()


def log_structured_error(
    error_type: str,
    message: str,
    exception: Exception = None,
    context: dict[str, Any] = None,
    level: int = logging.ERROR
) -> None:
    """Log an error with structured context and aggregation.

    This function provides comprehensive error logging with:
    - Structured context preservation
    - Error aggregation for pattern analysis
    - Clear, actionable error messages
    - Automatic alerting for high-frequency errors

    Args:
        error_type: Category of the error (e.g., 'network', 'auth', 'config')
        message: Descriptive error message
        exception: The exception that occurred (optional)
        context: Additional context data for debugging
        level: Logging level (default: ERROR)
    """
    # Build structured message
    structured_message = f"[{error_type.upper()}] {message}"

    # Add exception details if provided
    if exception:
        structured_message += f" | Exception: {type(exception).__name__}: {str(exception)}"

    # Add context if provided
    if context:
        context_str = " | ".join(f"{k}={v}" for k, v in context.items())
        structured_message += f" | Context: {context_str}"

    # Log the message
    logging.log(level, structured_message)

    # Record in aggregator
    error_aggregator.record_error(error_type, message, context)

    # Check for alerts
    if error_aggregator.should_alert(error_type):
        logging.critical(
            f"🚨 HIGH ERROR RATE ALERT: {error_type} occurring at "
            f"{error_aggregator.get_error_summary()[error_type]['rate_per_hour']:.1f}/hour"
        )


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
            "%(asctime)s %(log_color)s%(levelname)-8s%(reset)s %(message_log_color)s%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
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

        # Suppress websockets library debug messages
        logging.getLogger('websockets').setLevel(logging.INFO)

        # Apply formatter and filter to all existing handlers (in case any were added)
        for h in root_logger.handlers:
            h.setFormatter(formatter)
            h.addFilter(FseventsFilter())

        # Set up periodic error reporting (every 6 hours for long-running apps)
        self._setup_periodic_reporting()

        # Register exit handler for final error summary
        atexit.register(self._log_final_error_summary)

    def _setup_periodic_reporting(self):
        """Set up periodic error summary reporting."""
        def periodic_report():
            while True:
                time.sleep(6 * 3600)  # 6 hours
                try:
                    error_aggregator.log_summary_report()
                except Exception as e:
                    logging.error(f"Failed to generate periodic error report: {e}")

        # Start periodic reporting in background thread
        report_thread = threading.Thread(target=periodic_report, daemon=True)
        report_thread.start()

    def _log_final_error_summary(self):
        """Log final error summary on application exit."""
        try:
            logging.info("📊 Final error summary before shutdown:")
            error_aggregator.log_summary_report()
        except Exception as e:
            logging.error(f"Failed to log final error summary: {e}")
