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
    from ..auth_token.manager import TokenManager
    from ..color import ColorChangeService
    from ..color.models import ColorRequestResult  # forward ref for type hints

import aiohttp

from ..api.twitch import TwitchAPI
from ..application_context import ApplicationContext
from ..chat import BackendType, create_chat_backend
from ..config.async_persistence import flush_pending_updates, queue_user_update
from ..config.model import normalize_channels_list
from ..rate.retry_policies import (
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
    ) -> None:
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

        # Shared HTTP session (must be provided)
        if not http_session:
            raise ValueError(
                "http_session is required - bots must use shared HTTP session"
            )
        self.http_session = http_session
        self.api = TwitchAPI(self.http_session)

        # Registration / token manager will be set at runtime
        self.token_manager: TokenManager | None = None
        self._registrar: BotRegistrar | None = None

        # Channel / behavior config
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file
        self.enabled = enabled

        # Chat backend (EventSub)
        from ..chat import ChatBackend as _ChatBackend  # local import for type only

        self.chat_backend: _ChatBackend | None = (
            None  # lazy init via _initialize_connection
        )

        # Runtime state
        self.running = False
        self.listener_task: asyncio.Task[Any] | None = None
        self.stats = BotStats()
        self.last_color: str | None = None

        # Rate limiting & scheduling
        self.rate_limiter = context.get_rate_limiter(self.client_id, self.username)
        self.scheduler = AdaptiveScheduler()

        # Lazy/optional services
        self._color_service: ColorChangeService | None = None
        self._last_color_change_payload: dict[str, Any] | None = None
        # Track last user activity (for adaptive keepalive decisions elsewhere)
        self._last_activity_ts: float = time.time()
        self._keepalive_recent_activity: float = float(
            os.environ.get("COLOR_KEEPALIVE_RECENT_ACTIVITY_SECONDS", "600")
        )

    async def on_persistent_prime_detection(self) -> None:
        """Persist that this user should not use random hex colors.

        Sets is_prime_or_turbo to False in the user's config and writes via
        debounced queue. This method is invoked by ColorChangeService when
        repeated hex rejections indicate lack of Turbo/Prime privileges.
        """
        if not self.config_file:
            return
        user_config = self._build_user_config()
        user_config["is_prime_or_turbo"] = False
        try:
            await queue_user_update(user_config, self.config_file)
            logging.info(
                f"💾 Persisted Turbo/Prime detection (disabled random hex) user={self.username}"
            )
        except Exception as e:  # noqa: BLE001
            logging.warning(
                f"⚠️ Persist Turbo/Prime detection error user={self.username}: {str(e)}"
            )

    async def start(self) -> None:
        logging.info(f"▶️ Starting bot user={self.username}")
        self.running = True
        # ApplicationContext guarantees a token_manager; still guard defensively
        self.token_manager = self.context.token_manager
        if self.token_manager is None:  # pragma: no cover - defensive
            logging.error(f"❌ No token manager available user={self.username}")
            return
        self._registrar = BotRegistrar(self.token_manager)
        await self._registrar.register(self)
        # Register keepalive callback (piggyback on token manager periodic validation)
        try:
            if self.token_manager:
                self.token_manager.register_keepalive_callback(
                    self.username, self._maybe_get_color_keepalive
                )
        except Exception as e:  # noqa: BLE001
            logging.debug(
                f"⚠️ Keepalive callback register error user={self.username} error={str(e)}"
            )
        if not await self._initialize_connection():
            return
        await self._run_chat_loop()

    async def _run_chat_loop(self) -> None:
        """Run primary chat backend listen task (IRC or EventSub)."""
        backend = self.chat_backend
        if backend is None:
            logging.error(f"⚠️ Chat backend not initialized user={self.username}")
            return
        self._create_and_monitor_listener(backend)
        normalized_channels: list[str] = getattr(
            self, "_normalized_channels_cache", self.channels
        )
        await self._join_additional_channels(backend, normalized_channels)
        await self.scheduler.start()

        try:
            task = self.listener_task
            if task is not None:
                await task
        except KeyboardInterrupt:
            logging.warning(f"🔻 Shutting down bot user={self.username}")
        except Exception as e:  # noqa: BLE001
            await self._attempt_reconnect(e, self._listener_task_done)
        finally:
            await self.stop()

    def _create_and_monitor_listener(self, backend: Any) -> None:  # noqa: ANN401
        """Create listener task and attach error logging callback."""
        self.listener_task = asyncio.create_task(backend.listen())
        self.listener_task.add_done_callback(self._listener_task_done)

    def _listener_task_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            try:
                logging.error(
                    f"💥 Listener task error user={self.username} type={type(exc).__name__} error={str(exc)}"
                )
            except Exception as cb_e:  # noqa: BLE001
                logging.debug(
                    f"⚠️ Failed logging listener task error user={self.username}: {str(cb_e)}"
                )

    async def _join_additional_channels(
        self, backend: Any, normalized_channels: list[str]
    ) -> None:  # noqa: ANN401
        for channel in normalized_channels[1:]:
            try:
                await backend.join_channel(channel)
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"💥 Error joining channel {channel} user={self.username}: {str(e)}"
                )

    async def _attempt_reconnect(
        self, error: Exception, cb: Callable[[asyncio.Task[Any]], None]
    ) -> None:
        backoff = 1.0
        attempts = 0
        max_attempts = 5
        current_error = error
        while attempts < max_attempts and self.running:
            attempts += 1
            logging.warning(
                f"🔄 Listener crashed - reconnect attempt {attempts} backoff={round(backoff, 2)}s user={self.username} error={str(current_error)}"
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            try:
                if not await self._initialize_connection():
                    continue
                backend2 = self.chat_backend
                if backend2 is None:
                    current_error = RuntimeError(
                        "chat backend not initialized for reconnect"
                    )
                    continue
                self.listener_task = asyncio.create_task(backend2.listen())
                self.listener_task.add_done_callback(cb)
                await self.listener_task
                return
            except Exception as e2:  # noqa: BLE001
                current_error = e2
                continue

    async def stop(self) -> None:
        logging.warning(f"🛑 Stopping bot user={self.username}")
        self.running = False
        await self.scheduler.stop()
        await self._cancel_token_task()
        await self._disconnect_chat_backend()
        await self._wait_for_listener_task()
        # Flush any pending debounced config writes before final shutdown.
        if self.config_file:
            try:
                await flush_pending_updates(self.config_file)
            except Exception as e:  # noqa: BLE001
                # Log at debug to avoid noisy shutdown warnings; still visible for diagnostics.
                logging.debug(
                    f"⚠️ Error flushing pending config updates user={self.username}: {str(e)}"
                )
        self.running = False
        await asyncio.sleep(0.1)

    # Removed legacy PUT-based keepalive implementation in favor of GET-based callback
    # (_maybe_get_color_keepalive) triggered after token validation.

    async def _initialize_connection(self) -> bool:
        """Prepare identity, choose backend, connect, and register handlers."""
        if not await self._ensure_user_id():
            return False
        await self._prime_color_state()
        btype = BackendType.EVENTSUB
        logging.info(f"🔀 Using chat backend {btype.value} user={self.username}")
        await self._log_scopes_if_possible()
        normalized_channels = await self._normalize_channels_if_needed()
        if not await self._init_and_connect_backend(btype, normalized_channels):
            return False
        self._normalized_channels_cache = normalized_channels
        return True

    async def _ensure_user_id(self) -> bool:
        if self.user_id:
            return True
        user_info = await self._get_user_info()
        if user_info and "id" in user_info:
            self.user_id = user_info["id"]
            logging.debug(f"🆔 Retrieved user_id {self.user_id} user={self.username}")
            return True
        logging.error(f"❌ Failed to retrieve user_id user={self.username}")
        return False

    async def _prime_color_state(self) -> None:
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            logging.info(
                f"🎨 Initialized with current color {current_color} user={self.username}"
            )

    async def _log_scopes_if_possible(self) -> None:
        try:
            from ..api.twitch import TwitchAPI  # local import

            if self.context.session:
                api = TwitchAPI(self.context.session)
                validation = await api.validate_token(self.access_token)
                raw_scopes = (
                    validation.get("scopes") if isinstance(validation, dict) else None
                )
                scopes_list = (
                    [str(s) for s in raw_scopes] if isinstance(raw_scopes, list) else []
                )
                logging.info(
                    f"🧪 Token scopes user={self.username} scopes={';'.join(scopes_list) if scopes_list else '<none>'}"
                )
        except Exception as e:  # noqa: BLE001
            logging.debug(
                f"🚫 Token scope validation error user={self.username} missing={str(e)}"
            )

    async def _normalize_channels_if_needed(self) -> list[str]:
        normalized_channels, was_changed = normalize_channels_list(self.channels)
        if was_changed:
            logging.info(
                f"🛠️ Normalized channels old={len(self.channels)} new={len(normalized_channels)} user={self.username}"
            )
            self.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.channels = normalized_channels
        return normalized_channels

    async def _init_and_connect_backend(
        self, btype: BackendType, normalized_channels: list[str]
    ) -> bool:
        self.chat_backend = create_chat_backend(
            btype.value, http_session=self.context.session
        )
        backend = self.chat_backend
        # Route all messages (including commands like !rip) through a single handler
        # to avoid double triggers; do not attach a separate color_change_handler.
        backend.set_message_handler(self.handle_message)
        # Register token invalid callback for EventSub escalation
        if hasattr(backend, "set_token_invalid_callback"):
            try:
                backend.set_token_invalid_callback(self._check_and_refresh_token)
            except Exception as e:
                logging.warning(
                    f"⚠️ Failed to register EventSub backend callback user={self.username}: {str(e)}"
                )
        connected = await backend.connect(
            self.access_token,
            self.username,
            normalized_channels[0],
            self.user_id,
            self.client_id,
            self.client_secret,
        )
        if not connected:
            logging.error(f"❌ Failed to connect user={self.username}")
            return False
        # Ensure EventSub backend receives token updates after refreshes
        try:
            if self.token_manager:
                self.token_manager.register_eventsub_backend(self.username, backend)
        except Exception as e:  # noqa: BLE001
            logging.info(
                f"⚠️ Failed to register EventSub backend for token propagation user={self.username}: {str(e)}"
            )
        logging.debug(f"👂 Starting async message listener user={self.username}")
        return True

    async def _cancel_token_task(self) -> None:  # compatibility no-op
        return None

    async def _disconnect_chat_backend(self) -> None:
        backend = self.chat_backend
        if backend is not None:
            try:
                await backend.disconnect()
            except Exception as e:  # noqa: BLE001
                logging.warning(f"⚠️ Error disconnecting user={self.username}: {str(e)}")

    async def _wait_for_listener_task(self) -> None:
        if self.listener_task and not self.listener_task.done():
            try:
                await asyncio.wait_for(self.listener_task, timeout=2.0)
            except TimeoutError:
                logging.warning(
                    f"💥 Error waiting for listener task user={self.username}: timeout"
                )
                self.listener_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"💥 Error waiting for listener task user={self.username}: {str(e)}"
                )

    async def handle_message(self, sender: str, channel: str, message: str) -> None:
        if sender.lower() != self.username.lower():
            return
        self._last_activity_ts = time.time()
        self.stats.messages_sent += 1
        raw = message.strip()
        msg_lower = raw.lower()
        handled = await self._maybe_handle_toggle(msg_lower)
        if handled:
            return
        # Direct color command: "ccc <color>" (preset or hex, case-insensitive).
        if await self._maybe_handle_ccc(raw, msg_lower):
            return
        if self._is_color_change_allowed():
            await self._change_color()

    def _is_color_change_allowed(self) -> bool:
        return bool(getattr(self, "enabled", True))

    async def _maybe_handle_ccc(self, raw: str, msg_lower: str) -> bool:
        """Handle the ccc command and return True if processed.

        Behavior:
        - Accepts presets and hex (#rrggbb or 3-digit) case-insensitively.
        - Works even if auto mode is disabled.
        - If user is non-Prime/Turbo (use_random_colors=False), hex is ignored and an
          info event is logged.
        - Invalid/missing argument yields an info event and no action.
        """
        if not msg_lower.startswith("ccc"):
            return False
        parts = raw.split(None, 1)
        if len(parts) != 2:
            logging.info(f"ℹ️ Ignoring invalid ccc argument user={self.username} arg=")
            return True
        desired = self._normalize_color_arg(parts[1])
        if not desired:
            logging.info(
                f"ℹ️ Ignoring invalid ccc argument user={self.username} arg={parts[1]}"
            )
            return True
        if desired.startswith("#") and not getattr(self, "use_random_colors", True):
            logging.info(
                f"ℹ️ Ignoring hex via ccc for non-Prime user={self.username} color={desired}"
            )
            return True
        await self._change_color(desired)
        return True

    @staticmethod
    def _normalize_color_arg(arg: str) -> str | None:
        """Normalize a user-supplied color argument.

        Accepts preset names (case-insensitive) or hex with or without leading '#'.
        Returns a normalized string: preset name in lowercase, or '#rrggbb'.
        """
        from ..color.utils import TWITCH_PRESET_COLORS  # local import

        s = arg.strip()
        if not s:
            return None
        s_nohash = s[1:] if s.startswith(("#", "#")) else s
        lower = s_nohash.lower()
        # Preset name match
        if lower in {c.lower() for c in TWITCH_PRESET_COLORS}:
            return lower
        # Hex validation (3 or 6 chars)
        import re

        if re.fullmatch(r"[0-9a-fA-F]{6}", lower):
            return f"#{lower}"
        if re.fullmatch(r"[0-9a-fA-F]{3}", lower):
            # Expand shorthand (#abc -> #aabbcc)
            expanded = "".join(ch * 2 for ch in lower)
            return f"#{expanded}"
        return None

    async def _maybe_handle_toggle(self, msg_lower: str) -> bool:
        """Handle enable/disable commands; return True if processed."""
        if msg_lower not in {"ccd", "cce"}:
            return False
        target_enabled = msg_lower == "cce"
        currently_enabled = getattr(self, "enabled", True)
        if target_enabled == currently_enabled:
            return True  # Command redundant; treat as handled (no spam)
        self.enabled = target_enabled
        logging.info(
            f"✅ Automatic color change enabled user={self.username}"
            if target_enabled
            else f"🚫 Automatic color change disabled user={self.username}"
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
            logging.warning(
                f"⚠️ Failed to persist disable flag user={self.username}: {str(e)}"
                if not flag
                else f"⚠️ Failed to persist enable flag user={self.username}: {str(e)}"
            )

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        # Use attached TokenManager if available; otherwise fall back to context
        tm = self.token_manager or getattr(self.context, "token_manager", None)
        if not tm:
            return False
        # Cache for subsequent calls
        self.token_manager = tm
        try:
            outcome = await tm.ensure_fresh(self.username, force_refresh=force)
            info = tm.get_info(self.username)
            if info and info.access_token:
                if info.access_token != self.access_token:
                    self.access_token = info.access_token
                    backend_local = self.chat_backend
                    if backend_local is not None:
                        try:
                            backend_local.update_token(info.access_token)
                        except Exception as e:  # noqa: BLE001
                            logging.debug(
                                f"⚠️ Error updating chat backend tokens user={self.username}: {str(e)}"
                            )
                return outcome.name != "FAILED"
            return False
        except Exception as e:  # noqa: BLE001
            logging.error(
                f"💥 Error in token refresh helper user={self.username}: {str(e)}"
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
            logging.error(
                f"❌ Failed to get user info status={status_code} user={self.username}"
            )
            return None
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 Error getting user info user={self.username}: {str(e)}")
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
                        logging.info(
                            f"🎨 Current color is {color} user={self.username}"
                        )
                        return color
            elif status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            elif status_code == 401:
                return None
            logging.info(f"⚠️ No current color set user={self.username}")
            return None
        except Exception as e:  # noqa: BLE001
            logging.warning(
                f"💥 Error getting current color user={self.username}: {str(e)}"
            )
            return None

    # --- Color change low-level request (expected by ColorChangeService) ---
    async def _perform_color_request(
        self, params: dict[str, Any], *, action: str
    ) -> ColorRequestResult:  # noqa: D401
        """Issue a raw color change (PUT chat/color) returning structured result.

        This restores the method expected by ColorChangeService._issue_request.
        It encapsulates: rate limit accounting, status classification, logging
        of certain error diagnostics, and payload capture for later snippets.
        """
        from ..color.models import (  # local import
            ColorRequestResult,
            ColorRequestStatus,
        )

        await self.rate_limiter.wait_if_needed(action, is_user_request=True)
        try:
            data, status_code, headers = await self.api.request(
                "PUT",
                CHAT_COLOR_ENDPOINT,
                access_token=self.access_token,
                client_id=self.client_id,
                params=params,
            )
            self._last_color_change_payload = data if isinstance(data, dict) else None
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            # Success codes (Twitch may return 204 No Content or 200 OK)
            if status_code in (200, 204):
                return ColorRequestResult(
                    ColorRequestStatus.SUCCESS, http_status=status_code
                )
            if status_code == 401:
                return ColorRequestResult(
                    ColorRequestStatus.UNAUTHORIZED, http_status=status_code
                )
            if status_code == 429:
                return ColorRequestResult(
                    ColorRequestStatus.RATE_LIMIT, http_status=status_code
                )
            # Generic HTTP failure
            return ColorRequestResult(
                ColorRequestStatus.HTTP_ERROR,
                http_status=status_code,
                error=self._extract_color_error_snippet(),
            )
        except TimeoutError as e:  # network timeout
            return ColorRequestResult(ColorRequestStatus.TIMEOUT, error=str(e))
        except Exception as e:  # noqa: BLE001
            return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR, error=str(e))

    def increment_colors_changed(self) -> None:
        self.stats.colors_changed += 1

    async def _change_color(self, hex_color: str | None = None) -> bool:
        # Local import only when needed to avoid circular dependency at import time
        if self._color_service is None:
            from ..color import ColorChangeService  # local import

            self._color_service = ColorChangeService(self)
        return await self._color_service.change_color(hex_color)

    async def _maybe_get_color_keepalive(self) -> None:
        # Keepalive should run even if auto color changes are disabled; we just annotate enabled state.
        idle = time.time() - self._last_activity_ts
        if idle < self._keepalive_recent_activity:
            logging.info(
                f"🫧 Keepalive GET skipped (recent activity) user={self.username}"
            )
            return
        logging.info(f"🫧 Keepalive color GET attempt user={self.username}")
        try:
            color = await self._get_current_color_impl()
            if color:
                self.last_color = color
                logging.info(
                    f"🫧 Keepalive color GET success user={self.username} color={color}"
                )
            else:
                logging.info(
                    f"🫧 Keepalive color GET returned no color user={self.username}"
                )
                # If keepalive returns no color, force a token refresh and let
                # TokenManager propagate/persist via its update hook.
                try:
                    await self._check_and_refresh_token(force=True)
                except Exception as e:  # noqa: BLE001
                    logging.debug(
                        f"⚠️ Keepalive callback error user={self.username} error={str(e)}"
                    )
        except Exception as e:  # noqa: BLE001
            logging.debug(
                f"⚠️ Keepalive color GET error user={self.username} error={str(e)}"
            )
            # If keepalive fails, force a token refresh to surface issues early.
            try:
                await self._check_and_refresh_token(force=True)
            except Exception as e2:  # noqa: BLE001
                logging.debug(
                    f"⚠️ Keepalive callback error user={self.username} error={str(e2)}"
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
        logging.info(f"🔻 Closing bot user={self.username}")
        self.running = False

    def print_statistics(self) -> None:
        logging.info(
            f"📊 Statistics user={self.username} messages={self.stats.messages_sent} colors={self.stats.colors_changed}"
        )
