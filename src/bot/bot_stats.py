"""Lightweight statistics container for a Twitch bot.

Decouples stats storage from the main `TwitchColorBot` object to allow
future aggregation, persistence, or reset logic without touching the
core bot implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BotStats:
    messages_sent: int = 0
    colors_changed: int = 0

    def to_dict(self) -> dict[str, int]:  # pragma: no cover (simple helper)
        return {
            "messages_sent": self.messages_sent,
            "colors_changed": self.colors_changed,
        }
