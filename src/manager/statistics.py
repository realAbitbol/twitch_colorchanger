"""Statistics persistence helper for BotManager (moved from manager_statistics.py)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol


class _BotProto(Protocol):  # structural typing for consumers
    username: str
    messages_sent: int
    colors_changed: int

    def print_statistics(self) -> None: ...  # noqa: D401,E701


class ManagerStatistics:
    def save(self, bots: Iterable[_BotProto]) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
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
        restored = 0
        for bot in bots:
            if bot.username in saved:
                data = saved[bot.username]
                bot.messages_sent = data["messages_sent"]
                bot.colors_changed = data["colors_changed"]
                restored += 1
        if restored:
            logging.debug(f"♻️ Restored statistics (bots={restored})")

    def aggregate(self, bots: Iterable[_BotProto]) -> None:
        bots_list = list(bots)
        if not bots_list:
            return None
        total_messages = sum(bot.messages_sent for bot in bots_list)
        total_colors = sum(bot.colors_changed for bot in bots_list)
        logging.info(
            f"📊 Aggregate statistics bots={len(bots_list)} messages={total_messages} colors={total_colors}"
        )
        for bot in bots_list:
            bot.print_statistics()
