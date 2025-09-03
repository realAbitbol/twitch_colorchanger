"""Core TwitchColorBot implementation (moved from top-level bot.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..color import ColorChangeService
    from ..token.manager import TokenManager

import aiohttp

from ..api.twitch import TwitchAPI
from ..application_context import ApplicationContext
from ..color.models import ColorRequestResult, ColorRequestStatus
from ..config.async_persistence import (
    flush_pending_updates,
    queue_user_update,
)
from ..config.model import normalize_channels_list
from ..irc.async_irc import AsyncTwitchIRC
from ..logs.logger import logger
from ..rate.retry_policies import (
    COLOR_CHANGE_RETRY,
    DEFAULT_NETWORK_RETRY,
    run_with_retry,
)
from ..scheduler.adaptive_scheduler import AdaptiveScheduler
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
        self.token_manager: TokenManager | None = None  # set at start
        self._registrar: BotRegistrar | None = None
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file
        self.enabled = enabled
        self.irc: AsyncTwitchIRC | None = None
        self.running = False
        self.irc_task: asyncio.Task | None = None
        self.stats = BotStats()
        # Removed unused connection tracking attributes flagged by dead-code scan.
        # last_successful_connection / connection_failure_start were not referenced.
        self.last_color: str | None = None
        self.rate_limiter = context.get_rate_limiter(self.client_id, self.username)
        self.scheduler = AdaptiveScheduler()
        # Lazy-initialized optional services / state containers
        self._color_service: ColorChangeService | None = None
        self._last_color_change_payload: dict[str, Any] | None = None

    async def start(self) -> None:
        logger.log_event("bot", "start", user=self.username)
        self.running = True
        # ApplicationContext guarantees a token_manager; still guard defensively
        self.token_manager = self.context.token_manager
        if self.token_manager is None:  # pragma: no cover - defensive
            logger.log_event(
                "bot", "no_token_manager", level=logging.ERROR, user=self.username
            )
            return
        self._registrar = BotRegistrar(self.token_manager)
        await self._registrar.register(self)
        if not await self._initialize_connection():
            return
        await self._run_irc_loop()

    async def _run_irc_loop(self) -> None:
        """Run primary IRC listen task with limited auto-reconnect attempts."""
        if not self.irc:
            logger.log_event(
                "bot", "irc_not_initialized", level=logging.ERROR, user=self.username
            )
            return
        self.irc_task = asyncio.create_task(self.irc.listen())

        def _irc_task_done(task: asyncio.Task[Any]) -> None:  # local callback
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                try:
                    logger.log_event(
                        "bot",
                        "irc_listener_task_error",
                        level=logging.ERROR,
                        user=self.username,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                except Exception as cb_e:  # noqa: BLE001
                    logger.log_event(
                        "bot",
                        "irc_listener_task_log_fail",
                        level=logging.DEBUG,
                        user=self.username,
                        error=str(cb_e),
                    )

        self.irc_task.add_done_callback(_irc_task_done)
        normalized_channels: list[str] = getattr(
            self, "_normalized_channels_cache", self.channels
        )
        for channel in normalized_channels[1:]:
            await self.irc.join_channel(channel)
        await self.scheduler.start()

        try:
            await self.irc_task
        except KeyboardInterrupt:
            logger.log_event(
                "bot", "shutdown_initiated", level=logging.WARNING, user=self.username
            )
        except Exception as e:  # noqa: BLE001
            await self._attempt_reconnect(e, _irc_task_done)
        finally:
            await self.stop()

    async def _attempt_reconnect(
        self, error: Exception, cb: Callable[[asyncio.Task[Any]], None]
    ) -> None:
        backoff = 1.0
        attempts = 0
        max_attempts = 5
        current_error = error
        while attempts < max_attempts and self.running:
            attempts += 1
            logger.log_event(
                "bot",
                "irc_listener_crash_reconnect_attempt",
                level=logging.WARNING,
                user=self.username,
                attempt=attempts,
                error=str(current_error),
                backoff=round(backoff, 2),
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            try:
                if not await self._initialize_connection():
                    continue
                if not self.irc:
                    current_error = RuntimeError("IRC not initialized for reconnect")
                    continue
                self.irc_task = asyncio.create_task(self.irc.listen())
                self.irc_task.add_done_callback(cb)
                await self.irc_task
                return
            except Exception as e2:  # noqa: BLE001
                current_error = e2
                continue

    async def stop(self) -> None:
        logger.log_event("bot", "stopping", level=logging.WARNING, user=self.username)
        self.running = False
        await self.scheduler.stop()
        await self._cancel_token_task()
        await self._disconnect_irc()
        await self._wait_for_irc_task()
        # Flush any pending debounced config writes before final shutdown.
        if self.config_file:
            try:
                await flush_pending_updates(self.config_file)
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

    async def _initialize_connection(self) -> bool:
        """Prepare user id, color state, IRC client and connect. Returns success."""
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
                return False
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
        if hasattr(self.irc, "set_auth_failure_callback"):
            try:
                self.irc.set_auth_failure_callback(self._on_irc_auth_failure)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "auth_failure_callback_set_error",
                    level=logging.DEBUG,
                    user=self.username,
                    error=str(e),
                )
        if not await self.irc.connect(
            self.access_token, self.username, normalized_channels[0]
        ):
            logger.log_event(
                "bot", "connect_failed", level=logging.ERROR, user=self.username
            )
            return False
        logger.log_event("bot", "listener_start", user=self.username)
        # Provide normalized channels list to caller context (start method) via return attribute
        self._normalized_channels_cache: list[str] = normalized_channels
        return True

    async def _cancel_token_task(self) -> None:  # compatibility no-op
        return None

    async def _disconnect_irc(self) -> None:
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

    async def _wait_for_irc_task(self) -> None:
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

    async def handle_irc_message(self, sender: str, channel: str, message: str) -> None:
        if sender.lower() != self.username.lower():
            return
        self.stats.messages_sent += 1
        msg_lower = message.strip().lower()
        handled = await self._maybe_handle_toggle(msg_lower)
        if handled:
            return
        if self._is_color_change_allowed():
            await self._change_color()

    def _is_color_change_allowed(self) -> bool:
        return bool(getattr(self, "enabled", True))

    async def _maybe_handle_toggle(self, msg_lower: str) -> bool:
        """Handle enable/disable commands; return True if processed."""
        if msg_lower not in {"ccd", "cce"}:
            return False
        target_enabled = msg_lower == "cce"
        currently_enabled = getattr(self, "enabled", True)
        if target_enabled == currently_enabled:
            return True  # Command redundant; treat as handled (no spam)
        self.enabled = target_enabled
        logger.log_event(
            "bot",
            "auto_color_enabled" if target_enabled else "auto_color_disabled",
            user=self.username,
        )
        await self._persist_enabled_flag(target_enabled)
        return True

    async def _persist_enabled_flag(self, flag: bool) -> None:
        if not self.config_file:
            return
        user_config = self._build_user_config()
        user_config["enabled"] = flag
        try:
            await queue_user_update(user_config, self.config_file)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "persist_disable_failed" if not flag else "persist_enable_failed",
                level=logging.WARNING,
                user=self.username,
                error=str(e),
            )

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        if not self.token_manager:
            return False
        try:
            outcome = await self.token_manager.ensure_fresh(
                self.username, force_refresh=force
            )
            info = self.token_manager.get_info(self.username)
            if info and info.access_token:
                if info.access_token != self.access_token:
                    self.access_token = info.access_token
                    if self.irc:
                        self.irc.update_token(info.access_token)
                return outcome.name != "FAILED"
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

    async def _get_user_info(self) -> dict[str, Any] | None:
        async def op() -> dict[str, Any] | None:
            return await self._get_user_info_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_user_info_impl(self) -> dict[str, Any] | None:
        await self.rate_limiter.wait_if_needed("get_user_info", is_user_request=True)
        try:
            data, status_code, headers = await self.api.request(
                "GET", "users", access_token=self.access_token, client_id=self.client_id
            )
            self.rate_limiter.update_from_headers(headers, is_user_request=True)
            if status_code == 200 and data and data.get("data"):
                first = data["data"][0]
                if isinstance(first, dict):  # narrow type
                    return first
                return None
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

    async def _get_current_color(self) -> str | None:
        async def op() -> str | None:
            return await self._get_current_color_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_current_color_impl(self) -> str | None:
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
            if status_code == 200 and data and data.get("data"):
                first = data["data"][0]
                if isinstance(first, dict):
                    color = first.get("color")
                    if isinstance(color, str):
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

    async def _on_irc_auth_failure(self) -> None:
        if not self.token_manager:
            return None
        try:
            outcome = await self.token_manager.ensure_fresh(
                self.username, force_refresh=True
            )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "irc_auth_refresh_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return None
        info = self.token_manager.get_info(self.username)
        if info and info.access_token:
            self.access_token = info.access_token
            if self.irc:
                self.irc.update_token(info.access_token)
            if outcome.name != "FAILED":
                logger.log_event("bot", "irc_auth_refresh_success", user=self.username)
        return None

    def increment_colors_changed(self) -> None:
        self.stats.colors_changed += 1

    async def _change_color(self, hex_color: str | None = None) -> bool:
        # Local import only when needed to avoid circular dependency at import time
        if self._color_service is None:
            from ..color import ColorChangeService  # local import

            self._color_service = ColorChangeService(self)
        return await self._color_service.change_color(hex_color)

    async def _perform_color_request(
        self, params: dict, action: str
    ) -> ColorRequestResult:
        status_code = await self._execute_color_status_request(params, action)
        if isinstance(status_code, ColorRequestResult):  # error short-circuit
            return status_code
        return self._classify_color_status(status_code, action)

    async def _execute_color_status_request(
        self, params: dict[str, Any], action: str
    ) -> int | ColorRequestResult:
        async def op() -> int:
            await self.rate_limiter.wait_if_needed(action, is_user_request=True)
            data, status_code, headers = await asyncio.wait_for(
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
            # record last payload for diagnostics
            self._last_color_change_payload = data
            return status_code

        try:
            return await run_with_retry(
                op, COLOR_CHANGE_RETRY, user=self.username, log_domain="retry"
            )
        except TimeoutError:
            logger.log_event(
                "bot", "color_change_timeout", level=logging.ERROR, user=self.username
            )
            return ColorRequestResult(ColorRequestStatus.TIMEOUT)
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
            return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR, error=str(e))

    def _classify_color_status(
        self, status_code: int, action: str
    ) -> ColorRequestResult:
        if status_code == 204:
            return ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)
        if status_code == 429:
            return ColorRequestResult(ColorRequestStatus.RATE_LIMIT, http_status=429)
        if status_code == 401:
            return ColorRequestResult(ColorRequestStatus.UNAUTHORIZED, http_status=401)
        if 200 <= status_code < 300:
            return ColorRequestResult(
                ColorRequestStatus.SUCCESS, http_status=status_code
            )
        snippet = self._extract_color_error_snippet()
        if snippet:
            logger.log_event(
                "bot",
                "color_change_http_error_detail"
                if action != "preset_color"
                else "preset_color_http_error_detail",
                level=logging.DEBUG,
                user=self.username,
                status_code=status_code,
                detail=snippet,
            )
        return ColorRequestResult(
            ColorRequestStatus.HTTP_ERROR, http_status=status_code, error=snippet
        )

    def _extract_color_error_snippet(self) -> str | None:
        try:  # pragma: no cover - defensive
            payload: dict[str, Any] | None = self._last_color_change_payload
            if payload is None:
                return None
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
                base = message if message else payload
                return str(base)[:200]
        except Exception:  # noqa: BLE001
            return None

    def _get_rate_limit_display(self, debug_only: bool = False) -> str:
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

    def close(self) -> None:
        logger.log_event("bot", "closing_for_user", user=self.username)
        self.running = False

    def print_statistics(self) -> None:
        logger.log_event(
            "bot",
            "statistics",
            user=self.username,
            messages=self.stats.messages_sent,
            colors=self.stats.colors_changed,
        )
