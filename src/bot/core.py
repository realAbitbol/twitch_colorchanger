"""Core TwitchColorBot implementation (moved from top-level bot.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

import aiohttp

from api.twitch import TwitchAPI
from application_context import ApplicationContext
from config.async_persistence import (
    flush_pending_updates,
    queue_user_update,
)
from config.model import normalize_channels_list
from irc.async_irc import AsyncTwitchIRC
from logs.logger import logger
from rate.retry_policies import (
    COLOR_CHANGE_RETRY,
    DEFAULT_NETWORK_RETRY,
    run_with_retry,
)
from scheduler.adaptive_scheduler import AdaptiveScheduler

from . import BotPersistenceMixin, BotRegistrar, BotStats

CHAT_COLOR_ENDPOINT = "chat/color"


class TwitchColorBot(BotPersistenceMixin):  # pylint: disable=too-many-instance-attributes
    OAUTH_PREFIX = "oauth:"

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        context: ApplicationContext,
        token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        nick: str,
        channels: list[str],
        http_session: aiohttp.ClientSession,
        is_prime_or_turbo: bool = True,
        config_file: str | None = None,
        user_id: str | None = None,
        enabled: bool = True,
    ):
        self.context = context
        self.username = nick
        self.access_token = (
            token.replace(self.OAUTH_PREFIX, "")
            if token.startswith(self.OAUTH_PREFIX)
            else token
        )
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.token_expiry: datetime | None = None
        if not http_session:
            raise ValueError(
                "http_session is required - bots must use shared HTTP session"
            )
        self.http_session = http_session
        self.api = TwitchAPI(self.http_session)
        self.token_manager = None  # set at start
        self._registrar: BotRegistrar | None = None
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file
        self.enabled = enabled
        self.irc: AsyncTwitchIRC | None = None
        self.running = False
        self.irc_task: asyncio.Task | None = None
        self.stats = BotStats()
        self.last_successful_connection = time.time()
        self.connection_failure_start: float | None = None
        self.last_color: str | None = None
        self.rate_limiter = context.get_rate_limiter(self.client_id, self.username)
        self.scheduler = AdaptiveScheduler()

    async def start(self):
        logger.log_event("bot", "start", user=self.username)
        self.running = True
        self.token_manager = self.context.token_manager
        self._registrar = BotRegistrar(self.token_manager)
        await self._registrar.register(self)
        if not self.user_id:
            user_info = await self._get_user_info()
            if user_info and "id" in user_info:
                self.user_id = user_info["id"]
                logger.log_event(
                    "bot", "user_id_retrieved", user=self.username, user_id=self.user_id
                )
            else:
                logger.log_event(
                    "bot", "user_id_failed", level=logging.ERROR, user=self.username
                )
                return
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            logger.log_event(
                "bot", "initialized_color", user=self.username, color=current_color
            )
        logger.log_event("bot", "using_async_irc", user=self.username)
        self.irc = AsyncTwitchIRC()
        normalized_channels, was_changed = normalize_channels_list(self.channels)
        if was_changed:
            logger.log_event(
                "bot",
                "normalized_channels",
                user=self.username,
                old_count=len(self.channels),
                new_count=len(normalized_channels),
            )
            self.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.channels = normalized_channels
        self.irc.channels = normalized_channels.copy()
        self.irc.set_message_handler(self.handle_irc_message)
        try:
            self.irc.set_auth_failure_callback(self._on_irc_auth_failure)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        if not await self.irc.connect(
            self.access_token, self.username, normalized_channels[0]
        ):
            logger.log_event(
                "bot", "connect_failed", level=logging.ERROR, user=self.username
            )
            return
        logger.log_event("bot", "listener_start", user=self.username)
        self.irc_task = asyncio.create_task(self.irc.listen())
        for channel in normalized_channels[1:]:
            await self.irc.join_channel(channel)
        await self.scheduler.start()
        try:
            await self.irc_task
        except KeyboardInterrupt:
            logger.log_event(
                "bot", "shutdown_initiated", level=logging.WARNING, user=self.username
            )
        finally:
            await self.stop()

    async def stop(self):
        logger.log_event("bot", "stopping", level=logging.WARNING, user=self.username)
        self.running = False
        await self.scheduler.stop()
        await self._cancel_token_task()
        await self._disconnect_irc()
        await self._wait_for_irc_task()
        # Flush any pending debounced config writes before final shutdown.
        if getattr(self, "config_file", None):
            try:
                await flush_pending_updates(self.config_file)  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001
                # Log at debug to avoid noisy shutdown warnings; still visible for diagnostics.
                logger.log_event(
                    "bot",
                    "flush_pending_updates_error",
                    level=logging.DEBUG,
                    user=self.username,
                    error=str(e),
                )
        self.running = False
        await asyncio.sleep(0.1)

    async def _cancel_token_task(self):  # compatibility no-op
        pass

    async def _disconnect_irc(self):
        if self.irc:
            try:
                await self.irc.disconnect()
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "disconnect_error",
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

    async def _wait_for_irc_task(self):
        if self.irc_task and not self.irc_task.done():
            try:
                await asyncio.wait_for(self.irc_task, timeout=2.0)
            except TimeoutError:
                logger.log_event(
                    "bot",
                    "waiting_irc_task_error",
                    level=logging.WARNING,
                    user=self.username,
                    error="timeout",
                )
                self.irc_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "waiting_irc_task_error",
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

    async def handle_irc_message(self, sender: str, channel: str, message: str):
        if sender.lower() != self.username.lower():
            return
        self.stats.messages_sent += 1
        msg_lower = message.strip().lower()

        async def _persist_enabled(flag: bool, failure_event: str):
            if not self.config_file:
                return
            user_config = self._build_user_config()
            user_config["enabled"] = flag
            try:
                # Use debounced queue for rapid toggle spam.
                await queue_user_update(user_config, self.config_file)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    failure_event,
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

        if msg_lower == "ccd":
            if getattr(self, "enabled", True):
                self.enabled = False
                logger.log_event("bot", "auto_color_disabled", user=self.username)
                await _persist_enabled(False, "persist_disable_failed")
            return
        if msg_lower == "cce":
            if not getattr(self, "enabled", True):
                self.enabled = True
                logger.log_event("bot", "auto_color_enabled", user=self.username)
                await _persist_enabled(True, "persist_enable_failed")
            return
        if getattr(self, "enabled", True):
            await self._change_color()

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        if not self.token_manager:
            return False
        try:
            if force:
                await self.token_manager.force_refresh(self.username)
            else:
                await self.token_manager.get_fresh_token(self.username)
            info = self.token_manager.get_token_info(self.username)
            if info and info.access_token:
                if info.access_token != self.access_token:
                    self.access_token = info.access_token
                    if self.irc:
                        self.irc.update_token(info.access_token)
                return True
            return False
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "token_refresh_helper_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return False

    async def _get_user_info(self):
        async def op():
            return await self._get_user_info_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_user_info_impl(self):
        await self.rate_limiter.wait_if_needed("get_user_info", is_user_request=True)
        try:
            data, status_code, headers = await self.api.request(
                "GET", "users", access_token=self.access_token, client_id=self.client_id
            )
            self.rate_limiter.update_from_headers(headers, is_user_request=True)
            if status_code == 200 and data and data.get("data"):
                return data["data"][0]
            if status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            if status_code == 401:
                return None
            logger.log_event(
                "bot",
                "user_info_failed_status",
                level=logging.ERROR,
                user=self.username,
                status_code=status_code,
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "user_info_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return None

    async def _get_current_color(self):
        async def op() -> dict | None:
            return await self._get_current_color_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_current_color_impl(self):
        await self.rate_limiter.wait_if_needed(
            "get_current_color", is_user_request=True
        )
        try:
            params = {"user_id": self.user_id}
            data, status_code, headers = await self.api.request(
                "GET",
                CHAT_COLOR_ENDPOINT,
                access_token=self.access_token,
                client_id=self.client_id,
                params=params,
            )
            self.rate_limiter.update_from_headers(headers, is_user_request=True)
            if (
                status_code == 200
                and data
                and data.get("data")
                and len(data["data"]) > 0
            ):
                color = data["data"][0].get("color")
                if color:
                    logger.log_event(
                        "bot", "current_color_is", user=self.username, color=color
                    )
                    return color
            elif status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            elif status_code == 401:
                return None
            logger.log_event("bot", "no_current_color_set", user=self.username)
            return None
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "get_current_color_error",
                level=logging.WARNING,
                user=self.username,
                error=str(e),
            )
            return None

    async def _on_irc_auth_failure(self):
        try:
            if not hasattr(self, "token_manager"):
                return
            refreshed = await self.token_manager.force_refresh(self.username)
            info = self.token_manager.get_token_info(self.username)
            if info and info.access_token:
                self.access_token = info.access_token
                if self.irc:
                    self.irc.update_token(info.access_token)
                if refreshed:
                    logger.log_event(
                        "bot", "irc_auth_refresh_success", user=self.username
                    )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "irc_auth_failure_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )

    def increment_colors_changed(self) -> None:
        self.stats.colors_changed += 1

    async def _change_color(self, hex_color=None):
        from color import ColorChangeService  # local import

        if not hasattr(self, "_color_service"):
            self._color_service = ColorChangeService(self)  # type: ignore[attr-defined]
        return await self._color_service.change_color(hex_color)  # type: ignore[attr-defined]

    async def _perform_color_request(self, params: dict, action: str) -> int:
        async def op() -> int:
            await self.rate_limiter.wait_if_needed(action, is_user_request=True)
            _, status_code, headers = await asyncio.wait_for(
                self.api.request(
                    "PUT",
                    CHAT_COLOR_ENDPOINT,
                    access_token=self.access_token,
                    client_id=self.client_id,
                    params=params,
                ),
                timeout=10,
            )
            self.rate_limiter.update_from_headers(headers, is_user_request=True)
            return status_code

        try:
            return await run_with_retry(
                op, COLOR_CHANGE_RETRY, user=self.username, log_domain="retry"
            )
        except TimeoutError:
            logger.log_event(
                "bot", "color_change_timeout", level=logging.ERROR, user=self.username
            )
            return 0
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "preset_color_error"
                if action == "preset_color"
                else "error_changing_color_internal",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return 0

    def _get_rate_limit_display(self, debug_only=False):
        debug_enabled = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
        if debug_only and not debug_enabled:
            return ""
        if not self.rate_limiter.user_bucket:
            return " [rate limit info pending]"
        bucket = self.rate_limiter.user_bucket
        current_time = time.time()
        if current_time - bucket.last_updated > 60:
            return " [rate limit info stale]"
        remaining = bucket.remaining
        limit = bucket.limit
        reset_in = max(0, bucket.reset_timestamp - current_time)
        if remaining > 100:
            return f" [{remaining}/{limit} reqs]"
        if remaining > 10:
            return f" [{remaining}/{limit} reqs, reset in {reset_in:.0f}s]"
        return f" [⚠️ {remaining}/{limit} reqs, reset in {reset_in:.0f}s]"

    def close(self):
        logger.log_event("bot", "closing_for_user", user=self.username)
        self.running = False

    def print_statistics(self):
        logger.log_event(
            "bot",
            "statistics",
            user=self.username,
            messages=self.stats.messages_sent,
            colors=self.stats.colors_changed,
        )
