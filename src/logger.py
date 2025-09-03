"""
Simple colored logging system for the Twitch Color Changer bot
"""

import logging
import os
import sys

try:  # Local import; keep optional so logger works even if catalog missing early
    from .event_catalog import EVENT_TEMPLATES  # type: ignore
except Exception:  # pragma: no cover - fallback when catalog absent
    EVENT_TEMPLATES = {}


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

    # Removed legacy direct level methods (debug/info/warning/error/critical/exception)
    # to enforce structured logging via log_event exclusively.

    def log_event(
        self,
        domain: str,
        action: str,
        level: int = logging.INFO,
        human: str | None = None,
        exc_info: bool = False,
        **kwargs,
    ):
        """Log a structured event.

        Args:
            domain: Logical subsystem (e.g. 'token', 'irc').
            action: Specific action or outcome (e.g. 'refresh_success').
            level: Logging level (default INFO) if no heuristic mapping.
            human: Optional explicit human-readable message/template override.
            **kwargs: Structured context fields.
        """
        event_name = f"{domain}_{action}".lower()

        # Determine human-readable text
        human_text = human
        derived = False
        if human_text is None:
            template = EVENT_TEMPLATES.get((domain, action))
            if template:
                try:
                    human_text = template.format(**kwargs)
                except Exception:  # formatting failure fallback
                    human_text = template
            else:
                # Auto-generate readable fallback
                human_text = f"{domain.replace('_', ' ')}: {action.replace('_', ' ')}"
                derived = True

        # Attach human text into kwargs; mark if derived
        if human_text is not None:
            kwargs.setdefault("human", human_text)
        if derived:
            kwargs.setdefault("derived", True)

        self._log(level, event_name, exc_info=exc_info, **kwargs)

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


# Legacy print_log removed after structured logging migration.
