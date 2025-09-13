"""Reconnection helper logic (moved from `manager_reconnect.py`)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot
    from bot.manager import BotManager


async def reconnect_unhealthy_bots(
    manager: BotManager, bots: list[TwitchColorBot]
) -> None:
    logging.warning(f"🔄 Reconnecting unhealthy bots (count={len(bots)})")
    for bot in bots:
        success = await attempt_bot_reconnection(manager, bot)
        if success:
            logging.info(f"✅ Reconnected bot user={bot.username}")
        else:
            logging.error(f"❌ Failed to reconnect bot user={bot.username}")


async def attempt_bot_reconnection(manager: BotManager, bot: TwitchColorBot) -> bool:
    try:
        if not bot.chat_backend:
            logging.error(f"⚠️ No connection to reconnect user={bot.username}")
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
        logging.error(f"💥 Reconnection error user={bot.username}: {str(e)}")
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
            logging.info(f"✅ Bot became healthy before reconnect user={bot.username}")
            return True
    except Exception as e:  # noqa: BLE001
        logging.warning(f"💥 Pre-check health error user={bot.username}: {str(e)}")
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
        logging.warning(
            f"💥 Error cancelling old listener user={bot.username}: {str(e)}"
        )


async def force_bot_reconnect(bot: TwitchColorBot) -> bool:
    if not bot.chat_backend:
        logging.error(f"⚠️ No connection present for reconnect user={bot.username}")
        return False
    # For EventSub, reconnection is handled internally, so just check if healthy
    if hasattr(bot.chat_backend, "force_reconnect"):
        success = await bot.chat_backend.force_reconnect()
        if not success:
            logging.error(f"❌ Failed to reconnect bot user={bot.username}")
            return False
    try:
        task = getattr(bot, "listener_task", None)
        if task is not None and not task.done():
            task.cancel()
    except Exception:  # noqa: BLE001
        logging.debug(
            f"⚠️ Old listener cancellation raised non-critical exception user={bot.username}"
        )
    if bot.chat_backend:
        bot.listener_task = asyncio.create_task(bot.chat_backend.listen())
    # For EventSub, channels are handled internally
    return True


def start_fresh_listener(bot: TwitchColorBot) -> bool:
    if not bot.chat_backend:
        logging.error(f"❌ Cannot start listener user={bot.username}")
        return False
    try:
        bot.listener_task = asyncio.create_task(bot.chat_backend.listen())
        return True
    except Exception as e:  # noqa: BLE001
        logging.error(f"💥 Listener start failed user={bot.username}: {str(e)}")
        return False


async def wait_for_health(bot: TwitchColorBot) -> bool:
    for _ in range(30):
        await asyncio.sleep(0.1)
        try:
            if bot.chat_backend and bot.chat_backend.is_healthy():
                return True
        except Exception:  # noqa: BLE001
            break
    logging.warning(f"❌ Health not confirmed after reconnect user={bot.username}")
    return False
