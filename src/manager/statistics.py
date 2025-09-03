"""Statistics persistence helper for BotManager (moved from manager_statistics.py)."""

from __future__ import annotations

from logs.logger import logger


class ManagerStatistics:
    def save(self, bots) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for bot in bots:
            stats[bot.username] = {
                "messages_sent": bot.stats.messages_sent,
                "colors_changed": bot.stats.colors_changed,
            }
        logger.log_event("manager", "saved_statistics", level=10, bots=len(stats))
        return stats

    def restore(self, bots, saved: dict[str, dict[str, int]]):
        restored = 0
        for bot in bots:
            if bot.username in saved:
                data = saved[bot.username]
                bot.stats.messages_sent = data["messages_sent"]
                bot.stats.colors_changed = data["colors_changed"]
                restored += 1
        if restored:
            logger.log_event("manager", "restored_statistics", level=10, bots=restored)

    def aggregate(self, bots):
        if not bots:
            return
        total_messages = sum(bot.stats.messages_sent for bot in bots)
        total_colors = sum(bot.stats.colors_changed for bot in bots)
        logger.log_event(
            "manager",
            "aggregate_statistics",
            bots=len(bots),
            total_messages=total_messages,
            total_color_changes=total_colors,
        )
        for bot in bots:
            bot.print_statistics()
