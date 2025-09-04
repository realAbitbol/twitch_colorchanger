"""Encapsulates registration of a bot's credentials with the TokenManager.

This keeps registration / refresh bootstrap concerns out of the main
`TwitchColorBot.start` method, reducing its branching and making it more
testable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from ..token.manager import TokenManager
    from .core import TwitchColorBot


class BotRegistrar:
    def __init__(self, token_manager: TokenManager) -> None:
        self._tm = token_manager

    # No additional state currently required.

    async def register(self, bot: TwitchColorBot) -> None:
        # Register credentials with the token manager, set up persistence, then
        # trigger an initial freshness check (which may refresh + persist).
        logger.log_event("bot", "registering_token_manager", user=bot.username)
        self._upsert_token(bot)
        logger.log_event("token_manager", "registered", user=bot.username)
        self._register_persistence_hook(bot)
        await self._initial_refresh_and_persist(bot)

    def _upsert_token(self, bot: TwitchColorBot) -> None:
        # Delegate to TokenManager's internal helper for consistency.
        self._tm._upsert_token_info(  # noqa: SLF001
            username=bot.username,
            access_token=bot.access_token,
            refresh_token=bot.refresh_token,
            client_id=bot.client_id,
            client_secret=bot.client_secret,
            expiry=bot.token_expiry,
        )

    # Baseline lifetime intentionally left for manager to set upon refresh/validation.

    def _register_persistence_hook(self, bot: TwitchColorBot) -> None:
        try:
            self._tm.register_update_hook(bot.username, bot._persist_token_changes)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "register_hook_failed",
                level=logging.DEBUG,
                user=bot.username,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _initial_refresh_and_persist(self, bot: TwitchColorBot) -> None:
        outcome = await self._tm.ensure_fresh(bot.username)
        if not outcome:
            return
        info = self._tm.get_info(bot.username)
        if not info:
            return
        old_access = bot.access_token
        old_refresh = getattr(bot, "refresh_token", None)
        bot.access_token = info.access_token
        if getattr(info, "refresh_token", None):
            bot.refresh_token = info.refresh_token
        access_changed = bool(info.access_token and info.access_token != old_access)
        refresh_changed = bool(
            getattr(info, "refresh_token", None) and info.refresh_token != old_refresh
        )
        if access_changed or refresh_changed:
            try:
                await bot._persist_token_changes()
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "token_persist_error",
                    level=logging.DEBUG,
                    user=bot.username,
                    error=str(e),
                    error_type=type(e).__name__,
                )
