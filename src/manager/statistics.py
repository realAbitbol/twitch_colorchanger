"""Statistics persistence helper for BotManager (moved from manager_statistics.py)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol


class _BotProto(Protocol):
    """Protocol defining the interface for bot statistics.

    This protocol ensures that bot objects provide the necessary attributes
    and methods for statistics management.

    Attributes:
        username: The bot's username.
        messages_sent: Number of messages sent by the bot.
        colors_changed: Number of color changes performed by the bot.
    """

    username: str
    messages_sent: int
    colors_changed: int

    def print_statistics(self) -> None: ...  # noqa: D401,E701


class ManagerStatistics:
    """Manages saving, restoring, and aggregating bot statistics.

    This class provides methods to persist bot statistics to a dictionary,
    restore them from a saved state, and compute aggregate statistics across
    multiple bots.
    """

    def save(self, bots: Iterable[_BotProto]) -> dict[str, dict[str, int]]:
        """Saves current statistics for all bots to a dictionary.

        Iterates through the provided bots and captures their current
        messages_sent and colors_changed counts.

        Args:
            bots: An iterable of bot objects conforming to _BotProto.

        Returns:
            A dictionary mapping bot usernames to their statistics.
        """
        stats: dict[str, dict[str, int]] = {}  # Initialize stats dictionary
        for bot in bots:
            stats[bot.username] = {
                "messages_sent": bot.messages_sent,
                "colors_changed": bot.colors_changed,
            }
        logging.debug(f"💾 Saved statistics (bots={len(stats)})")
        return stats

    def restore(
        self, bots: Iterable[_BotProto], saved: dict[str, dict[str, int]]
    ) -> None:
        """Restores bot statistics from a saved dictionary.

        Updates each bot's statistics if their username exists in the saved data.
        Only restores statistics for bots present in both the iterable and saved dict.

        Args:
            bots: An iterable of bot objects to restore statistics for.
            saved: A dictionary of saved statistics keyed by username.
        """
        restored = 0  # Counter for successfully restored bots
        for bot in bots:
            if bot.username in saved:
                data = saved[bot.username]
                bot.messages_sent = data["messages_sent"]
                bot.colors_changed = data["colors_changed"]
                restored += 1
        if restored:
            logging.debug(f"♻️ Restored statistics (bots={restored})")

    def aggregate(self, bots: Iterable[_BotProto]) -> None:
        """Aggregates and logs total statistics across all bots.

        Computes total messages sent and colors changed, logs the aggregate,
        and calls print_statistics on each bot.

        Args:
            bots: An iterable of bot objects to aggregate statistics for.
        """
        bots_list = list(bots)  # Convert to list for multiple iterations
        if not bots_list:
            return None  # No bots to aggregate
        total_messages = sum(bot.messages_sent for bot in bots_list)
        total_colors = sum(bot.colors_changed for bot in bots_list)
        logging.info(
            f"📊 Aggregate statistics bots={len(bots_list)} messages={total_messages} colors={total_colors}"
        )
        for bot in bots_list:
            bot.print_statistics()
