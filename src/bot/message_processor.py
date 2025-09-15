"""MessageProcessor class for TwitchColorBot - handles incoming messages and commands."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..color.utils import TWITCH_PRESET_COLORS
from ..config.async_persistence import queue_user_update

if TYPE_CHECKING:
    from .core import TwitchColorBot

# Pre-compiled regex patterns for performance
_HEX_6_PATTERN = re.compile(r"[0-9a-fA-F]{6}")
_HEX_3_PATTERN = re.compile(r"[0-9a-fA-F]{3}")


class MessageProcessor:
    """Processes incoming chat messages and commands."""

    def __init__(self, bot: TwitchColorBot) -> None:
        """Initialize the message processor.

        Args:
            bot: The TwitchColorBot instance this processor belongs to.
        """
        self.bot = bot

    async def handle_message(
        self,
        sender: str,
        _channel: str,
        message: str,
    ) -> None:
        """Handle incoming chat messages.

        Processes messages sent by the bot user, handling toggle commands,
        color change commands, and triggering automatic color changes.

        Args:
            sender: Username of the message sender.
            channel: Channel where the message was sent.
            message: The message content.
        """
        try:
            if sender.lower() != self.bot.username.lower():
                return
            raw = message.strip()
            msg_lower = raw.lower()
            handled = await self._maybe_handle_toggle(msg_lower)
            if handled:
                return
            # Direct color command: "ccc <color>" (preset or hex, case-insensitive).
            if await self._maybe_handle_ccc(raw, msg_lower):
                return
            if self._is_color_change_allowed():
                await self.bot.color_changer._change_color()  # type: ignore
        except Exception as e:
            logging.error(f"Error handling message from {sender}: {e}")

    def _is_color_change_allowed(self) -> bool:
        """Check if automatic color changes are currently allowed.

        Returns:
            True if enabled, False otherwise.
        """
        return bool(getattr(self.bot, "enabled", True))

    async def _maybe_handle_ccc(self, raw: str, msg_lower: str) -> bool:
        """Handle the ccc command and return True if processed.

        Behavior:
        - Accepts presets and hex (#rrggbb or 3-digit) case-insensitively.
        - Works even if auto mode is disabled.
        - If user is non-Prime/Turbo (use_random_colors=False), hex is ignored and an
          info event is logged.
        - Invalid/missing argument yields an info event and no action.
        """
        if not msg_lower.startswith("ccc"):
            return False
        parts = raw.split(None, 1)
        if len(parts) != 2:
            logging.info(
                f"ℹ️ Ignoring invalid ccc command (missing argument) user={self.bot.username}"
            )
            return True
        desired = self._normalize_color_arg(parts[1])
        if not desired:
            logging.info(
                f"ℹ️ Ignoring invalid ccc argument user={self.bot.username} arg={parts[1]}"
            )
            return True
        if desired.startswith("#") and not getattr(self.bot, "use_random_colors", True):
            logging.info(
                f"ℹ️ Ignoring hex via ccc for non-Prime user={self.bot.username} color={desired}"
            )
            return True
        await self.bot.color_changer._change_color(desired)  # type: ignore
        return True

    @staticmethod
    def _normalize_color_arg(arg: str) -> str | None:
        """Normalize a user-supplied color argument.

        Accepts preset names (case-insensitive) or hex with or without leading '#'.
        Returns a normalized string: preset name in lowercase, or '#rrggbb'.
        """
        s = arg.strip()
        if not s:
            return None
        s_nohash = s[1:] if s.startswith("#") else s
        lower = s_nohash.lower()
        # Preset name match
        if lower in {c.lower() for c in TWITCH_PRESET_COLORS}:
            return lower
        # Hex validation (3 or 6 chars)
        if _HEX_6_PATTERN.fullmatch(lower):
            return f"#{lower}"
        if _HEX_3_PATTERN.fullmatch(lower):
            # Expand shorthand (#abc -> #aabbcc)
            expanded = "".join(ch * 2 for ch in lower)
            return f"#{expanded}"
        return None

    async def _maybe_handle_toggle(self, msg_lower: str) -> bool:
        """Handle enable/disable commands; return True if processed."""
        if msg_lower not in {"ccd", "cce"}:
            return False
        target_enabled = msg_lower == "cce"
        currently_enabled = getattr(self.bot, "enabled", True)
        if target_enabled == currently_enabled:
            return True  # Command redundant; treat as handled (no spam)
        self.bot.enabled = target_enabled
        logging.info(
            f"🖍️ Automatic color change enabled for user {self.bot.username}"
            if target_enabled
            else f"🚫 Automatic color change disabled for user {self.bot.username}"
        )
        await self._persist_enabled_flag(target_enabled)
        return True

    async def _persist_enabled_flag(self, flag: bool) -> None:
        """Persist the enabled flag to configuration.

        Args:
            flag: The enabled state to persist.
        """
        if not self.bot.config_file:
            return
        user_config = self.bot._build_user_config()
        user_config["enabled"] = flag
        try:
            await queue_user_update(user_config, self.bot.config_file)
        except Exception as e:
            logging.warning(f"Persist flag error: {str(e)}")
