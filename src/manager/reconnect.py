"""Reconnection helper logic (moved from `manager_reconnect.py`)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot
    from bot.manager import BotManager


async def reconnect_unhealthy_bots(manager: BotManager, bots: list[TwitchColorBot]):
    logger.log_event("manager", "reconnecting_unhealthy", level=30, count=len(bots))
    for bot in bots:
        success = await attempt_bot_reconnection(manager, bot)
        if success:
            logger.log_event("manager", "reconnected_bot", user=bot.username)
        else:
            logger.log_event("manager", "reconnect_failed", level=40, user=bot.username)


async def attempt_bot_reconnection(manager: BotManager, bot: TwitchColorBot) -> bool:
    try:
        if not bot.irc:
            logger.log_event(
                "manager", "no_irc_for_reconnect", level=40, user=bot.username
            )
            return False
        lock = get_bot_reconnect_lock(bot)
        async with lock:
            if bot_became_healthy(bot):
                return True
            await cancel_stale_listener(bot)
            if not await force_bot_reconnect(bot):
                return False
            if not start_fresh_listener(bot):
                return False
            return await wait_for_health(bot)
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "manager", "reconnect_error", level=40, user=bot.username, error=str(e)
        )
        return False


def get_bot_reconnect_lock(bot: TwitchColorBot):
    if not hasattr(bot, "_reconnect_lock"):
        import asyncio as _asyncio

        bot._reconnect_lock = _asyncio.Lock()  # type: ignore[attr-defined]
    return bot._reconnect_lock  # type: ignore[attr-defined]


def bot_became_healthy(bot: TwitchColorBot) -> bool:
    try:
        if bot.irc and bot.irc.is_healthy():
            logger.log_event(
                "manager", "bot_healthy_before_reconnect", user=bot.username
            )
            return True
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "manager",
            "precheck_health_error",
            level=30,
            user=bot.username,
            error=str(e),
        )
    return False


async def cancel_stale_listener(bot: TwitchColorBot):
    if not hasattr(bot, "irc_task") or bot.irc_task is None:
        return
    try:
        if not bot.irc_task.done():
            bot.irc_task.cancel()
            try:
                await asyncio.wait_for(bot.irc_task, timeout=1.5)
            except (TimeoutError, asyncio.CancelledError):
                pass
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "manager",
            "old_listener_cancel_error",
            level=30,
            user=bot.username,
            error=str(e),
        )


async def force_bot_reconnect(bot: TwitchColorBot) -> bool:
    if not bot.irc:
        logger.log_event(
            "manager", "no_irc_for_force_reconnect", level=40, user=bot.username
        )
        return False
    success = await bot.irc.force_reconnect()
    if not success:
        logger.log_event("manager", "irc_reconnect_failed", level=40, user=bot.username)
        return False
    try:
        task = getattr(bot, "irc_task", None)
        if task is not None and not task.done():
            task.cancel()
    except Exception:  # noqa: BLE001
        logger.log_event(
            "manager", "old_listener_cancel_noncritical", level=10, user=bot.username
        )
    if bot.irc:
        bot.irc_task = asyncio.create_task(bot.irc.listen())
    for channel in bot.irc.channels[1:] if bot.irc else []:  # type: ignore[operator]
        try:
            if bot.irc:
                await bot.irc.join_channel(channel)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "manager",
                "failed_rejoin_channel",
                level=30,
                user=bot.username,
                channel=channel,
                error=str(e),
            )
    return True


def start_fresh_listener(bot: TwitchColorBot) -> bool:
    try:
        if not bot.irc:
            logger.log_event(
                "manager", "cannot_start_listener", level=40, user=bot.username
            )
            return False
        bot.irc_task = asyncio.create_task(bot.irc.listen())  # type: ignore[attr-defined]
        return True
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "manager",
            "listener_start_failed",
            level=40,
            user=bot.username,
            error=str(e),
        )
        return False


async def wait_for_health(bot: TwitchColorBot) -> bool:
    for _ in range(30):
        await asyncio.sleep(0.1)
        try:
            if bot.irc and bot.irc.is_healthy():
                return True
        except Exception:  # noqa: BLE001
            break
    logger.log_event("manager", "health_not_confirmed", level=30, user=bot.username)
    return False
