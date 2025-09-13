"""Logger implementation (moved to logging package)."""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO


def _supports_color(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except Exception:  # pragma: no cover
        return False


class SimpleFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: "\x1b[36m",
        logging.INFO: "\x1b[32m",
        logging.WARNING: "\x1b[33m",
        logging.ERROR: "\x1b[31m",
        logging.CRITICAL: "\x1b[35m",
    }
    RESET = "\x1b[0m"

    def __init__(self) -> None:
        super().__init__()
        # Guard against environments where stdout might be replaced.
        self.enable_color = _supports_color(sys.stdout)

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 (simple override)
        msg = record.getMessage()
        # Fixed width for level names so the following prefix column aligns.
        # Longest built-in level name: 'CRITICAL' (8 chars).
        raw_level = record.levelname.ljust(8)
        if self.enable_color:
            color = self.LEVEL_COLORS.get(record.levelno, "")
            reset = self.RESET
            return f"{color}{raw_level}{reset} {msg}"
        return f"{raw_level} {msg}"


class BotLogger:
    def __init__(
        self, name: str = "twitch_colorchanger", log_file: str | None = None
    ) -> None:
        # Fixed width for event name column when in debug (alignment)
        self._event_name_width = 32
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

    def set_level(self, level: int) -> None:
        self.logger.setLevel(level)

    def log_event(
        self,
        domain: str,
        action: str,
        level: int = logging.INFO,
        human: str | None = None,
        *,
        exc_info: bool = False,
        **kwargs: object,
    ) -> None:
        event_name = f"{domain}_{action}".lower()
        human_text = human
        derived = False
        if human_text is None:
            # Local import to avoid cyclic import issues during module init.
            try:  # pragma: no cover - defensive
                from .event_catalog import EVENT_TEMPLATES as _event_templates
            except Exception:  # noqa: BLE001
                _event_templates = {}
            template = _event_templates.get((domain, action))
            if template:
                try:
                    human_text = template.format(**kwargs)
                except Exception:  # noqa: BLE001
                    human_text = template
            else:
                human_text = f"{domain.replace('_', ' ')}: {action.replace('_', ' ')}"
                derived = True
        if human_text is not None:
            kwargs.setdefault("_human_text", human_text)
        if derived:
            kwargs.setdefault("derived", True)
        self._log(level, event_name, exc_info=exc_info, **kwargs)

    def _log(
        self, level: int, event_name: str, exc_info: bool = False, **kwargs: object
    ) -> None:
        debug_enabled = self._is_debug_enabled()
        kw: dict[str, object] = dict(kwargs)  # copy for mutation in extract
        user, channel, human_text = self._extract_reserved(kw)
        prefix = self._build_prefix(user, channel)
        msg = (
            self._build_debug_message(event_name, prefix, human_text, channel, kw)
            if debug_enabled
            else self._build_concise_message(event_name, prefix, human_text, channel)
        )
        self.logger.log(level, msg, exc_info=exc_info)

    @staticmethod
    def _is_debug_enabled() -> bool:
        return os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

    @staticmethod
    def _extract_reserved(
        kwargs: dict[str, object],
    ) -> tuple[str | None, str | None, str | None]:
        user_o = kwargs.pop("user", None)
        channel_o = kwargs.pop("channel", None)
        human_text_o = kwargs.pop("_human_text", None) or kwargs.get("human")
        kwargs.pop("human", None)
        user = str(user_o) if isinstance(user_o, str) else None
        channel = str(channel_o) if isinstance(channel_o, str) else None
        human_text = str(human_text_o) if isinstance(human_text_o, str) else None
        return user, channel, human_text

    @staticmethod
    def _build_prefix(user: str | None, channel: str | None) -> str:
        # Build raw label then pad to fixed width for alignment
        user_label = user or "system"
        core = f"{user_label}#{channel}" if channel else user_label
        # Choose a width that fits typical 'username#channel' combos
        padded = core.ljust(24)[:24]
        return f"[{padded}]"

    @staticmethod
    def _build_debug_message(
        event_name: str,
        prefix: str,
        human_text: str | None,
        channel: str | None,
        kwargs: dict[str, object],
    ) -> str:
        # Chat message beautification in DEBUG: include channel inline for PRIVMSG.
        if event_name == "chat_privmsg" and human_text:
            if channel:
                if human_text.startswith("💬 "):
                    human_text = f"💬 #{channel} {human_text[2:].lstrip()}"
                else:
                    human_text = f"💬 #{channel} {human_text}"
            elif not human_text.startswith("💬"):
                human_text = f"💬 {human_text}"
        context = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        # Pad / truncate event name to a fixed column for alignment
        width = 32
        if len(event_name) <= width:
            ev = event_name.ljust(width)
        else:  # truncate but keep rightmost indicator
            ev = event_name[: width - 1] + "…"
        base = f"{ev} {prefix}"
        if human_text:
            base = f"{base} {human_text}"
        if context:
            base = f"{base} ({context})"
        return base

    @staticmethod
    def _build_concise_message(
        event_name: str, prefix: str, human_text: str | None, channel: str | None
    ) -> str:
        # Chat message beautification: include channel before username for PRIVMSG.
        if event_name == "chat_privmsg" and human_text:
            if channel:
                # Desired format: "💬 #channel username: message"
                if human_text.startswith("💬 "):
                    human_text = f"💬 #{channel} {human_text[2:].lstrip()}"
                else:
                    human_text = f"💬 #{channel} {human_text}"
            elif not human_text.startswith("💬"):
                human_text = f"💬 {human_text}"
        core = human_text or event_name
        msg = f"{prefix} {core}"
        # Suffix channel hint is no longer necessary for PRIVMSG since it's in-line above.
        return msg


logger = BotLogger()
