"""Reconnection helper logic (moved from `manager_reconnect.py`)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot
    from bot.manager import BotManager


async def reconnect_unhealthy_bots(
    manager: BotManager, bots: list[TwitchColorBot]
) -> None:
    logger.log_event("manager", "reconnecting_unhealthy", level=30, count=len(bots))
    for bot in bots:
        success = await attempt_bot_reconnection(manager, bot)
        if success:
            logger.log_event("manager", "reconnected_bot", user=bot.username)
        else:
            logger.log_event("manager", "reconnect_failed", level=40, user=bot.username)


async def attempt_bot_reconnection(manager: BotManager, bot: TwitchColorBot) -> bool:
    try:
        if not bot.chat_backend:
            logger.log_event(
                "manager", "no_connection_for_reconnect", level=40, user=bot.username
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


def get_bot_reconnect_lock(bot: TwitchColorBot) -> asyncio.Lock:
    lock = getattr(bot, "_reconnect_lock", None)
    if lock is None:
        lock = asyncio.Lock()
    # Dynamically attach a private lock attribute; bots created without one will get it lazily.
    bot._reconnect_lock = lock
    return lock


def bot_became_healthy(bot: TwitchColorBot) -> bool:
    try:
        if bot.chat_backend and bot.chat_backend.is_healthy():
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


async def cancel_stale_listener(bot: TwitchColorBot) -> None:
    if not hasattr(bot, "listener_task") or bot.listener_task is None:
        return
    try:
        if not bot.listener_task.done():
            bot.listener_task.cancel()
            try:
                await asyncio.wait_for(bot.listener_task, timeout=1.5)
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
    if not bot.chat_backend:
        logger.log_event(
            "manager", "no_connection_for_force_reconnect", level=40, user=bot.username
        )
        return False
    # For EventSub, reconnection is handled internally, so just check if healthy
    if hasattr(bot.chat_backend, "force_reconnect"):
        success = await bot.chat_backend.force_reconnect()
        if not success:
            logger.log_event("manager", "reconnect_failed", level=40, user=bot.username)
            return False
    try:
        task = getattr(bot, "listener_task", None)
        if task is not None and not task.done():
            task.cancel()
    except Exception:  # noqa: BLE001
        logger.log_event(
            "manager", "old_listener_cancel_noncritical", level=10, user=bot.username
        )
    if bot.chat_backend:
        bot.listener_task = asyncio.create_task(bot.chat_backend.listen())
    # For EventSub, channels are handled internally
    return True


def start_fresh_listener(bot: TwitchColorBot) -> bool:
    if not bot.chat_backend:
        logger.log_event(
            "manager", "cannot_start_listener", level=40, user=bot.username
        )
        return False
    try:
        bot.listener_task = asyncio.create_task(bot.chat_backend.listen())
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
            if bot.chat_backend and bot.chat_backend.is_healthy():
                return True
        except Exception:  # noqa: BLE001
            break
    logger.log_event("manager", "health_not_confirmed", level=30, user=bot.username)
    return False
