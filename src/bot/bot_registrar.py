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
        logger.log_event("bot", "registering_token_manager", user=bot.username)
        self._tm.register(
            bot.username,
            bot.access_token,
            bot.refresh_token,
            bot.client_id,
            bot.client_secret,
            bot.token_expiry,
        )
        # Register persistence hook for future background refreshes.
        try:
            self._tm.register_update_hook(bot.username, bot._persist_token_changes)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "register_hook_failed",
                level=logging.DEBUG,
                user=bot.username,
                error=str(e),
                error_type=type(e).__name__,
            )
        outcome = await self._tm.ensure_fresh(bot.username)
        if outcome:
            info = self._tm.get_info(bot.username)
            if not info:
                return
            old_access = bot.access_token  # type: ignore[attr-defined]
            old_refresh = getattr(bot, "refresh_token", None)
            # Update bot with possibly refreshed tokens
            bot.access_token = info.access_token  # type: ignore[union-attr,attr-defined]
            if getattr(info, "refresh_token", None):  # type: ignore[attr-defined]
                bot.refresh_token = info.refresh_token  # type: ignore[attr-defined]
            # Persist only if tokens actually changed
            if (info.access_token and info.access_token != old_access) or (
                getattr(info, "refresh_token", None)
                and info.refresh_token != old_refresh  # type: ignore[attr-defined]
            ):
                # Best-effort persistence; failures already logged inside helper.
                try:
                    await bot._persist_token_changes()  # type: ignore[attr-defined]
                except Exception as e:  # noqa: BLE001
                    logger.log_event(
                        "bot",
                        "token_persist_error",
                        level=logging.DEBUG,
                        user=bot.username,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
