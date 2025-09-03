"""Encapsulates registration of a bot's credentials with the TokenManager.

This keeps registration / refresh bootstrap concerns out of the main
`TwitchColorBot.start` method, reducing its branching and making it more
testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from .bot import TwitchColorBot
    from .token_manager import TokenManager


class BotRegistrar:
    def __init__(self, token_manager: TokenManager) -> None:
        self._tm = token_manager

    async def register(self, bot: TwitchColorBot) -> None:
        logger.log_event("bot", "registering_token_manager", user=bot.username)
        self._tm.register_user(
            username=bot.username,
            access_token=bot.access_token,
            refresh_token=bot.refresh_token,
            client_id=bot.client_id,
            client_secret=bot.client_secret,
            expiry=bot.token_expiry,
        )
        fresh = await self._tm.get_fresh_token(bot.username)
        if fresh:
            bot.access_token = fresh
