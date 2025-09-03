"""
Simple colored logging system for the Twitch Color Changer bot
"""

import logging
import os
import sys


class SimpleFormatter(logging.Formatter):
    """Formatter without color codes (colors removed after migration)."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        message = record.getMessage()
        context_parts = []
        if hasattr(record, "user"):
            context_parts.append(f"user={record.user}")
        if hasattr(record, "channel"):
            context_parts.append(f"channel={record.channel}")
        if context_parts:
            message = f"{message} [{', '.join(context_parts)}]"
        if record.exc_info:
            message += f"\n{self.formatException(record.exc_info)}"
        return message


class BotLogger:
    """Project logger with lightweight structured event support.

    Conventions:
      * Prefer logger.log_event(domain="token", action="refresh_success", user=username, latency_ms=123)
      * Falls back to level methods (info/debug/...) for free-form messages.
      * log_event builds a canonical event name '<domain>_<action>' and attaches any extra
        kwargs as key=value pairs appended to the message (until a JSON formatter is added).
    """

    def __init__(self, name: str = "twitch_colorchanger", log_file: str | None = None):
        self.logger = logging.getLogger(name)
        self.log_file = log_file
        self.logger.handlers.clear()
        debug_enabled = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
        self.logger.setLevel(logging.DEBUG if debug_enabled else logging.INFO)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(SimpleFormatter())
        self.logger.addHandler(console_handler)

        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(file_handler)

    def set_level(self, level: int):
        self.logger.setLevel(level)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs):
        self._log(logging.ERROR, message, exc_info=exc_info, **kwargs)

    def critical(self, message: str, exc_info: bool = False, **kwargs):
        self._log(logging.CRITICAL, message, exc_info=exc_info, **kwargs)

    def exception(self, message: str, **kwargs):
        """Log an exception with traceback (compat shim for std logging API)."""
        self._log(logging.ERROR, message, exc_info=True, **kwargs)

    def log_event(self, domain: str, action: str, level: int = logging.INFO, **kwargs):
        event_name = f"{domain}_{action}".lower()
        self._log(level, event_name, **kwargs)

    def _log(self, level: int, message: str, exc_info: bool = False, **kwargs):
        extra: dict[str, str] = {}
        if "user" in kwargs:
            extra["user"] = kwargs.pop("user")
        if "channel" in kwargs:
            extra["channel"] = kwargs.pop("channel")
        if kwargs:
            context_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            message = f"{message} ({context_str})"
        self.logger.log(level, message, exc_info=exc_info, extra=extra)


# Global logger instance
logger = BotLogger()


# Backward compatibility functions
def print_log(
    message: str, color: str = "", debug_only: bool = False
):  # pragma: no cover
    """Legacy stub retained temporarily (stdout banner still uses utils)."""
    del color
    if debug_only:
        logger.debug(message)
    else:
        logger.info(message)
