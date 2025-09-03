"""Encapsulates registration of a bot's credentials with the TokenManager.

This keeps registration / refresh bootstrap concerns out of the main
`TwitchColorBot.start` method, reducing its branching and making it more
testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_logging.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from auth_token.manager import TokenManager

    from .core import TwitchColorBot


class BotRegistrar:
    def __init__(self, token_manager: TokenManager) -> None:
        self._tm = token_manager

    async def register(self, bot: TwitchColorBot) -> None:
        logger.log_event("bot", "registering_token_manager", user=bot.username)
        self._tm.register(
            bot.username,
            bot.access_token,
            bot.refresh_token,
            bot.client_id,
            bot.client_secret,
            bot.token_expiry,
        )
        outcome = await self._tm.ensure_fresh(bot.username)
        if outcome:
            bot.access_token = self._tm.get_info(bot.username).access_token  # type: ignore[union-attr]
