"""Project logging package.

Contains internal logging utilities (event catalog + BotLogger). Avoid
importing stdlib logging through this package name externally.
"""

from .event_catalog import EVENT_TEMPLATES, reload_event_templates  # noqa: F401
from .logger import BotLogger, logger  # noqa: F401

__all__ = ["BotLogger", "logger", "EVENT_TEMPLATES", "reload_event_templates"]
