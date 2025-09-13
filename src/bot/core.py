"""Core TwitchColorBot implementation (moved from top-level bot.py)."""

from __future__ import annotations

import asyncio
import logging
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
from ..chat import EventSubChatBackend
from ..config.async_persistence import (
    async_update_user_in_config,
    flush_pending_updates,
    queue_user_update,
)
from ..config.model import normalize_channels_list

CHAT_COLOR_ENDPOINT = "chat/color"


class TwitchColorBot:  # pylint: disable=too-many-instance-attributes
    """Core bot class for managing Twitch color changes.

    Handles authentication, chat connection, message processing, and color change logic
    for a single Twitch user. Integrates with EventSub for real-time chat events and
    manages token refresh, configuration persistence, and error recovery.

    Attributes:
        context: Application context providing shared services.
        username: Twitch username for the bot.
        access_token: Current OAuth access token.
        refresh_token: OAuth refresh token for token renewal.
        client_id: Twitch API client ID.
        client_secret: Twitch API client secret.
        user_id: Twitch user ID.
        channels: List of channels to join.
        use_random_colors: Whether to use random hex colors (Prime/Turbo users).
        config_file: Path to configuration file for persistence.
        enabled: Whether automatic color changes are enabled.
        running: Runtime state flag.
        messages_sent: Counter for sent messages.
        colors_changed: Counter for color changes.
        last_color: Last set color.
    """

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
        """Initialize the TwitchColorBot instance.

        Args:
            context: Application context with shared services.
            token: Initial OAuth access token (may include 'oauth:' prefix).
            refresh_token: OAuth refresh token for renewal.
            client_id: Twitch API client ID.
            client_secret: Twitch API client secret.
            nick: Twitch username.
            channels: List of channel names to join.
            http_session: Shared aiohttp ClientSession.
            is_prime_or_turbo: Whether user has Prime/Turbo for hex colors.
            config_file: Path to config file for persistence.
            user_id: Optional pre-known Twitch user ID.
            enabled: Whether to enable automatic color changes.
        """
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

        # Channel / behavior config
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file
        self.enabled = enabled

        # Chat backend (EventSub)
        self.chat_backend: EventSubChatBackend | None = (
            None  # lazy init via _initialize_connection
        )

        # Runtime state
        self.running = False
        self.listener_task: asyncio.Task[Any] | None = None
        self.messages_sent = 0
        self.colors_changed = 0
        self.last_color: str | None = None

        # Lazy/optional services
        self._color_service: ColorChangeService | None = None
        self._last_color_change_payload: dict[str, Any] | None = None

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
        except Exception as e:
            logging.warning(f"Persist detection error: {str(e)}")

    async def start(self) -> None:
        """Start the bot's main execution loop.

        Initializes token management, establishes chat connection, and begins
        listening for messages. Handles setup failures gracefully by stopping
        early if critical components cannot be initialized.
        """
        logging.info(f"▶️ Starting bot user={self.username}")
        self.running = True
        if not self._setup_token_manager():
            return
        await self._handle_initial_token_refresh()
        if not await self._initialize_connection():
            return
        await self._run_chat_loop()

    def _setup_token_manager(self) -> bool:
        """Set up and register with token manager. Returns False on failure."""
        # ApplicationContext guarantees a token_manager; still guard defensively
        self.token_manager = self.context.token_manager
        if self.token_manager is None:  # pragma: no cover - defensive
            logging.error(f"❌ No token manager available user={self.username}")
            return False
        # Register credentials with the token manager
        self.token_manager._upsert_token_info(  # noqa: SLF001
            username=self.username,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=self.token_expiry,
        )
        logging.debug(f"📝 Token manager: registered user={self.username}")
        try:
            self.token_manager.register_update_hook(
                self.username, self._persist_token_changes
            )
        except Exception as e:
            logging.debug(f"Token hook registration failed: {str(e)}")
        return True

    async def _handle_initial_token_refresh(self) -> None:
        """Handle initial token refresh and persistence."""
        if self.token_manager is None:
            raise RuntimeError("Token manager not initialized")
        outcome = await self.token_manager.ensure_fresh(self.username)
        if not outcome:
            return
        info = self.token_manager.get_info(self.username)
        if not info:
            return
        old_access = self.access_token
        old_refresh = getattr(self, "refresh_token", None)
        self.access_token = info.access_token
        if getattr(info, "refresh_token", None):
            self.refresh_token = info.refresh_token
        access_changed = bool(info.access_token and info.access_token != old_access)
        refresh_changed = bool(
            getattr(info, "refresh_token", None) and info.refresh_token != old_refresh
        )
        if access_changed or refresh_changed:
            try:
                await self._persist_token_changes()
            except Exception as e:
                logging.debug(f"Token persistence error: {str(e)}")

    async def _run_chat_loop(self) -> None:
        """Run primary EventSub chat backend listen task."""
        backend = self.chat_backend
        if backend is None:
            logging.error(f"⚠️ Chat backend not initialized user={self.username}")
            return
        self._create_and_monitor_listener(backend)
        normalized_channels: list[str] = getattr(
            self, "_normalized_channels_cache", self.channels
        )
        await self._join_additional_channels(backend, normalized_channels)

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
        """Callback for listener task completion.

        Logs errors if the task failed, with defensive error handling for logging
        failures themselves.

        Args:
            task: The completed asyncio task.
        """
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
        """Join additional channels beyond the first.

        Iterates through normalized channels starting from the second and attempts
        to join each. Logs warnings for join failures but continues with others.

        Args:
            backend: Chat backend instance.
            normalized_channels: List of normalized channel names.
        """
        for channel in normalized_channels[1:]:
            try:
                await backend.join_channel(channel)
            except Exception as e:
                logging.warning(f"Error joining channel {channel}: {str(e)}")

    async def _attempt_reconnect(
        self,
        error: Exception,
        cb: Callable[[asyncio.Task[Any]], None],
        *,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        max_attempts: int = 5,
    ) -> None:
        """Attempt to reconnect chat backend with exponential backoff.

        Retries connection initialization up to max_attempts with increasing delays.
        Stops if bot is no longer running or reconnection succeeds.

        Args:
            error: The original exception that triggered reconnection.
            cb: Callback to attach to new listener task.
            initial_backoff: Initial delay in seconds.
            max_backoff: Maximum delay in seconds.
            max_attempts: Maximum number of reconnection attempts.
        """
        backoff = initial_backoff
        attempts = 0
        current_error = error
        while attempts < max_attempts and self.running:
            attempts += 1
            logging.warning(
                f"🔄 Listener crashed - reconnect attempt {attempts} backoff={round(backoff, 2)}s user={self.username} error={str(current_error)}"
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
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
        """Stop the bot and clean up resources.

        Disconnects chat backend, waits for listener task to finish, flushes
        pending config updates, and sets running flag to False.
        """
        logging.warning(f"🛑 Stopping bot user={self.username}")
        self.running = False
        await self._disconnect_chat_backend()
        await self._wait_for_listener_task()
        if self.config_file:
            try:
                await flush_pending_updates(self.config_file)
            except Exception as e:
                logging.debug(f"Config flush error: {str(e)}")
        self.running = False
        await asyncio.sleep(0.1)

    async def _initialize_connection(self) -> bool:
        """Prepare identity, choose backend, connect, and register handlers."""
        if not await self._ensure_user_id():
            return False
        await self._prime_color_state()
        logging.info(f"🔀 Using EventSub chat backend user={self.username}")
        await self._log_scopes_if_possible()
        normalized_channels = await self._normalize_channels_if_needed()
        if not await self._init_and_connect_backend(normalized_channels):
            return False
        self._normalized_channels_cache = normalized_channels
        return True

    async def _ensure_user_id(self) -> bool:
        """Ensure user_id is available, fetching from API if needed.

        Returns:
            True if user_id is available or successfully retrieved, False otherwise.
        """
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
        """Initialize last_color with the user's current chat color.

        Fetches the current color from Twitch API and sets it as the last known color.
        """
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            logging.info(
                f"🎨 Initialized with current color {current_color} user={self.username}"
            )

    async def _log_scopes_if_possible(self) -> None:
        """Log the scopes of the current access token if possible.

        Validates the token with Twitch API and logs the associated scopes.
        Silently handles validation failures.
        """
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
        """Normalize channel names and persist if changed.

        Applies channel normalization rules and updates config if necessary.

        Returns:
            List of normalized channel names.
        """
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

    async def _init_and_connect_backend(self, normalized_channels: list[str]) -> bool:
        """Initialize and connect the chat backend.

        Creates EventSub backend, sets up message handlers, connects to the first
        channel, and registers with token manager.

        Args:
            normalized_channels: List of normalized channel names.

        Returns:
            True if connection successful, False otherwise.
        """
        self.chat_backend = EventSubChatBackend(http_session=self.context.session)
        backend = self.chat_backend
        # Route all messages (including commands like !rip) through a single handler
        # to avoid double triggers; do not attach a separate color_change_handler.
        backend.set_message_handler(self.handle_message)
        if hasattr(backend, "set_token_invalid_callback"):
            try:
                backend.set_token_invalid_callback(self._check_and_refresh_token)
            except Exception as e:
                logging.warning(f"Backend callback error: {str(e)}")
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
        try:
            if self.token_manager:
                self.token_manager.register_eventsub_backend(self.username, backend)
        except Exception as e:
            logging.info(f"EventSub backend registration error: {str(e)}")
        logging.debug(f"👂 Starting async message listener user={self.username}")
        return True

    async def _disconnect_chat_backend(self) -> None:
        """Disconnect the chat backend if connected.

        Attempts to gracefully disconnect the EventSub backend.
        """
        backend = self.chat_backend
        if backend is not None:
            try:
                await backend.disconnect()
            except Exception as e:
                logging.warning(f"Disconnect error: {str(e)}")

    async def _wait_for_listener_task(self) -> None:
        """Wait for the listener task to complete with timeout.

        Waits up to 2 seconds for the task to finish, cancels on timeout.
        """
        if self.listener_task and not self.listener_task.done():
            try:
                await asyncio.wait_for(self.listener_task, timeout=2.0)
            except TimeoutError:
                self.listener_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.warning(f"Listener task error: {str(e)}")

    async def handle_message(self, sender: str, channel: str, message: str) -> None:
        """Handle incoming chat messages.

        Processes messages sent by the bot user, handling toggle commands,
        color change commands, and triggering automatic color changes.

        Args:
            sender: Username of the message sender.
            channel: Channel where the message was sent.
            message: The message content.
        """
        if sender.lower() != self.username.lower():
            return
        self.messages_sent += 1
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
        """Check if automatic color changes are currently allowed.

        Returns:
            True if enabled, False otherwise.
        """
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
        """Persist the enabled flag to configuration.

        Args:
            flag: The enabled state to persist.
        """
        if not self.config_file:
            return
        user_config = self._build_user_config()
        user_config["enabled"] = flag
        try:
            await queue_user_update(user_config, self.config_file)
        except Exception as e:
            logging.warning(f"Persist flag error: {str(e)}")

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        """Check and refresh the access token if needed.

        Ensures the token is fresh and updates the backend if token changed.

        Args:
            force: Force token refresh even if not expired.

        Returns:
            True if token is valid/fresh, False otherwise.
        """
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
                        except Exception as e:
                            logging.debug(f"Backend token update error: {str(e)}")
                return outcome.name != "FAILED"
            return False
        except Exception as e:
            logging.error(f"Token refresh error: {str(e)}")
            return False

    async def _get_user_info(self) -> dict[str, Any] | None:
        """Fetch user information from Twitch API.

        Returns:
            User info dict or None if failed.
        """
        return await self._get_user_info_impl()

    async def _make_user_info_request(self) -> tuple[dict[str, Any] | None, int]:
        """Make the actual API request for user info.

        Returns:
            Tuple of (response data, status code).
        """
        data, status_code, _ = await self.api.request(
            "GET",
            "users",
            access_token=self.access_token,
            client_id=self.client_id,
        )
        return data, status_code

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for retries.

        Args:
            attempt: Current attempt number (0-based).

        Returns:
            Delay in seconds, capped at 60.
        """
        return min(1 * (2**attempt), 60)

    async def _get_user_info_impl(self) -> dict[str, Any] | None:
        """Implementation of user info fetching with retries.

        Handles API errors and retries with exponential backoff.

        Returns:
            User info dict or None if all attempts failed.
        """
        for attempt in range(6):
            try:
                data, status_code = await self._make_user_info_request()
                result = self._process_user_info_response(data, status_code, attempt)
                if (
                    result is None
                    and attempt < 5
                    and (status_code == 429 or status_code >= 500)
                ):
                    await asyncio.sleep(self._calculate_retry_delay(attempt))
                    continue
                return result
            except Exception as e:  # noqa: BLE001
                if attempt < 5:
                    await asyncio.sleep(self._calculate_retry_delay(attempt))
                    continue
                logging.error(
                    f"💥 Error getting user info user={self.username}: {str(e)}"
                )
                return None
        return None

    def _process_user_info_response(
        self, data: dict[str, Any] | None, status_code: int, attempt: int
    ) -> dict[str, Any] | None:
        """Process the response from user info API request.

        Args:
            data: Response data dict.
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            User info dict or None for retry/error.
        """
        if (
            status_code == 200
            and data
            and isinstance(data.get("data"), list)
            and data["data"]
        ):
            first = data["data"][0]
            if isinstance(first, dict):
                return first
            return None
        if status_code == 401:
            return None
        if attempt < 5 and (status_code == 429 or status_code >= 500):
            return None  # indicate retry
        logging.error(
            f"❌ Failed to get user info status={status_code} user={self.username}"
        )
        return None

    async def _get_current_color(self) -> str | None:
        """Fetch the user's current chat color from Twitch API.

        Returns:
            Color string or None if failed.
        """
        return await self._get_current_color_impl()

    async def _get_current_color_impl(self) -> str | None:
        """Implementation of current color fetching with retries.

        Handles API errors and retries with exponential backoff.

        Returns:
            Color string or None if all attempts failed.
        """
        for attempt in range(6):
            try:
                data, status_code = await self._make_color_request()
                result = self._process_color_response(data, status_code, attempt)
                if (
                    result is None
                    and attempt < 5
                    and (status_code == 429 or status_code >= 500)
                ):
                    await asyncio.sleep(self._calculate_retry_delay(attempt))
                    continue
                return result
            except Exception as e:  # noqa: BLE001
                if attempt < 5:
                    await asyncio.sleep(self._calculate_retry_delay(attempt))
                    continue
                logging.warning(
                    f"💥 Error getting current color user={self.username}: {str(e)}"
                )
                return None
        return None

    async def _make_color_request(self) -> tuple[dict[str, Any] | None, int]:
        """Make the actual API request for current color.

        Returns:
            Tuple of (response data, status code).
        """
        params = {"user_id": self.user_id}
        data, status_code, _ = await self.api.request(
            "GET",
            CHAT_COLOR_ENDPOINT,
            access_token=self.access_token,
            client_id=self.client_id,
            params=params,
        )
        return data, status_code

    def _process_color_response(
        self, data: dict[str, Any] | None, status_code: int, attempt: int
    ) -> str | None:
        """Process the response from color API request.

        Args:
            data: Response data dict.
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            Color string or None for retry/error.
        """
        if status_code == 200 and data and data.get("data"):
            first = data["data"][0]
            if isinstance(first, dict):
                color = first.get("color")
                if isinstance(color, str):
                    logging.info(f"🎨 Current color is {color} user={self.username}")
                    return color
        if status_code == 401:
            return None
        if attempt < 5 and (status_code == 429 or status_code >= 500):
            return None  # indicate retry
        logging.info(f"⚠️ No current color set user={self.username}")
        return None

    # --- Color change low-level request (expected by ColorChangeService) ---
    async def _perform_color_request(
        self, params: dict[str, Any], *, action: str
    ) -> ColorRequestResult:  # noqa: D401
        """Issue a raw color change (PUT chat/color) returning structured result.

        This restores the method expected by ColorChangeService._issue_request.
        It encapsulates: status classification, logging
        of certain error diagnostics, and payload capture for later snippets.
        """
        from ..color.models import (  # local import
            ColorRequestResult,
            ColorRequestStatus,
        )

        logging.debug(f"Performing color request action={action} user={self.username}")

        for attempt in range(6):
            try:
                data, status_code, _ = await self.api.request(
                    "PUT",
                    CHAT_COLOR_ENDPOINT,
                    access_token=self.access_token,
                    client_id=self.client_id,
                    params=params,
                )
                self._last_color_change_payload = (
                    data if isinstance(data, dict) else None
                )

                result = self._handle_color_response(status_code, attempt)
                if result is not None:
                    return result
                # retry
                delay = self._calculate_retry_delay(attempt)
                await asyncio.sleep(delay)
            except Exception as e:
                result = self._handle_color_exception(e, attempt)
                if result is not None:
                    return result
                # retry
                delay = self._calculate_retry_delay(attempt)
                await asyncio.sleep(delay)
        # exhausted
        return ColorRequestResult(
            ColorRequestStatus.INTERNAL_ERROR, error="Max retries exceeded"
        )

    def _handle_color_response(
        self, status_code: int, attempt: int
    ) -> ColorRequestResult | None:
        """Handle HTTP response for color change request.

        Args:
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            ColorRequestResult or None for retry.
        """
        from ..color.models import (  # local import
            ColorRequestResult,
            ColorRequestStatus,
        )

        if status_code in (200, 204):
            return ColorRequestResult(
                ColorRequestStatus.SUCCESS, http_status=status_code
            )
        elif status_code == 401:
            return ColorRequestResult(
                ColorRequestStatus.UNAUTHORIZED, http_status=status_code
            )
        elif status_code == 429 and attempt < 5:
            return None  # retry
        elif status_code == 429:
            return ColorRequestResult(
                ColorRequestStatus.RATE_LIMIT, http_status=status_code
            )
        elif status_code >= 500 and attempt < 5:
            return None  # retry
        elif status_code >= 500:
            return ColorRequestResult(
                ColorRequestStatus.HTTP_ERROR,
                http_status=status_code,
                error=self._extract_color_error_snippet(),
            )
        return ColorRequestResult(
            ColorRequestStatus.HTTP_ERROR,
            http_status=status_code,
            error=self._extract_color_error_snippet(),
        )

    def _handle_color_exception(
        self, e: Exception, attempt: int
    ) -> ColorRequestResult | None:
        """Handle exceptions during color change request.

        Args:
            e: The exception that occurred.
            attempt: Current attempt number.

        Returns:
            ColorRequestResult or None for retry.
        """
        from ..color.models import (  # local import
            ColorRequestResult,
            ColorRequestStatus,
        )

        if attempt < 5:
            return None  # retry
        if isinstance(e, TimeoutError):
            return ColorRequestResult(ColorRequestStatus.TIMEOUT, error=str(e))
        return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR, error=str(e))

    def increment_colors_changed(self) -> None:
        """Increment the counter for successful color changes."""
        self.colors_changed += 1

    async def _change_color(self, hex_color: str | None = None) -> bool:
        """Change the user's chat color.

        Args:
            hex_color: Specific color to set, or None for random.

        Returns:
            True if color change was successful.
        """
        # Local import only when needed to avoid circular dependency at import time
        if self._color_service is None:
            from ..color import ColorChangeService  # local import

            self._color_service = ColorChangeService(self)
        return await self._color_service.change_color(hex_color)

    async def _persist_token_changes(self) -> None:
        """Persist updated token information to configuration."""
        if not self._validate_config_prerequisites():
            return
        user_config = self._build_user_config()
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):
                return

    async def _persist_normalized_channels(self) -> None:
        """Persist normalized channel list to configuration."""
        config_file = getattr(self, "config_file", None)
        if config_file is None:
            return
        user_config = self._build_user_config()
        # Overwrite channels explicitly
        user_config["channels"] = self.channels
        try:
            await queue_user_update(user_config, config_file)
        except Exception as e:
            logging.warning(f"Persist channels error: {str(e)}")

    def _validate_config_prerequisites(self) -> bool:
        """Validate that required config fields are present for persistence.

        Returns:
            True if all prerequisites are met.
        """
        if not getattr(self, "config_file", None):
            logging.warning(
                f"📁 No config file specified cannot persist tokens user={self.username}"
            )
            return False
        if not getattr(self, "access_token", None):
            logging.warning(f"⚠️ Cannot save empty access token user={self.username}")
            return False
        if not getattr(self, "refresh_token", None):
            logging.warning(f"⚠️ Cannot save empty refresh token user={self.username}")
            return False
        return True

    def _build_user_config(self) -> dict[str, Any]:
        """Build user configuration dict from current instance state.

        Returns:
            Dict containing all user configuration fields.
        """
        # Direct attribute access; mixin consumer guarantees these attributes.
        username = self.username
        channels = self.channels
        return {
            "username": username,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "channels": channels,
            "is_prime_or_turbo": self.use_random_colors,
            "enabled": getattr(self, "enabled", True),
        }

    async def _attempt_config_save(
        self, user_config: dict[str, Any], attempt: int, max_retries: int
    ) -> bool:
        """Attempt to save user config with error handling.

        Args:
            user_config: Configuration dict to save.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            True if save was successful.
        """
        config_file = self.config_file
        if config_file is None:
            return False
        try:
            success = await async_update_user_in_config(user_config, config_file)
            if success:
                logging.info(f"💾 Token changes saved user={self.username}")
                return True
            # Fall through to generic handling below to trigger retries
            raise RuntimeError("update_user_in_config returned False")
        except FileNotFoundError:
            logging.error(
                f"📁 Config file not found path={self.config_file} user={self.username}"
            )
            return True
        except PermissionError:
            logging.error(f"🔒 Permission denied writing config user={self.username}")
            return True
        except Exception as e:
            return await self._handle_config_save_error(e, attempt, max_retries)

    async def _handle_config_save_error(
        self, error: Exception, attempt: int, max_retries: int
    ) -> bool:
        """Handle config save errors with retry logic.

        Args:
            error: The exception that occurred.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            True if should stop retrying, False to retry.
        """
        if attempt < max_retries - 1:
            logging.warning(f"Config save retry {attempt + 1}: {str(error)}")
            await asyncio.sleep(0.1 * (attempt + 1))
            return False
        else:
            logging.error(
                f"Config save failed after {max_retries} attempts: {str(error)}"
            )
            return True

    def _extract_color_error_snippet(self) -> str | None:
        """Extract error message from last color change response.

        Returns:
            Error message string or None if not available.
        """
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

    def close(self) -> None:
        """Close the bot and mark as not running."""
        logging.info(f"🔻 Closing bot user={self.username}")
        self.running = False

    def print_statistics(self) -> None:
        """Log current bot statistics."""
        logging.info(
            f"📊 Statistics user={self.username} messages={self.messages_sent} colors={self.colors_changed}"
        )
