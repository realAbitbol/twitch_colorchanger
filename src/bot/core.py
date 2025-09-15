"""Core TwitchColorBot implementation (moved from top-level bot.py)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..auth_token.manager import TokenManager

import aiohttp

from ..api.twitch import TwitchAPI
from ..application_context import ApplicationContext
from ..chat import EventSubChatBackend
from ..config.async_persistence import (
    flush_pending_updates,
)
from .color_changer import ColorChanger
from .message_handler import MessageHandler
from .token_refresher import TokenRefresher


class TwitchColorBot(MessageHandler, ColorChanger, TokenRefresher):  # pylint: disable=too-many-instance-attributes
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
        token_expiry: datetime | None = None,
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
            token_expiry: Optional token expiry datetime.
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
        self.token_expiry = token_expiry

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
        # Ensure '#' prefix is preserved in channels for consistency
        self.channels = [ch if ch.startswith("#") else f"#{ch}" for ch in channels]
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file
        self.enabled = enabled

        # Chat backend (EventSub)
        self.chat_backend: EventSubChatBackend | None = (
            None  # lazy init via _initialize_connection
        )

        # Runtime state
        self.running = False
        self._state_lock = asyncio.Lock()
        self.listener_task: asyncio.Task[None] | None = None
        self.last_color = None

        # Lazy/optional services
        self._color_service = None
        self._last_color_change_payload: dict[str, Any] | None = None

        # Initialize color cache
        self._init_color_cache()

    async def start(self) -> None:
        """Start the bot's main execution loop.

        Initializes token management, establishes chat connection, and begins
        listening for messages. Handles setup failures gracefully by stopping
        early if critical components cannot be initialized.
        """
        logging.info(f"▶️ Starting bot user={self.username}")
        async with self._state_lock:
            self.running = True
        if not self._setup_token_manager():
            async with self._state_lock:
                self.running = False
            return
        await self._handle_initial_token_refresh()
        if not await self._initialize_connection():
            async with self._state_lock:
                self.running = False
            return
        await self._run_chat_loop()

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

    def _create_and_monitor_listener(self, backend: EventSubChatBackend) -> None:
        """Create listener task and attach error logging callback."""
        self.listener_task = asyncio.create_task(backend.listen())
        self.listener_task.add_done_callback(self._listener_task_done)

    def _listener_task_done(self, task: asyncio.Task[None]) -> None:
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
        self, backend: EventSubChatBackend, normalized_channels: list[str]
    ) -> None:
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
        cb: Callable[[asyncio.Task[None]], None],
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
                async with self._state_lock:
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
        async with self._state_lock:
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
        logging.debug(f"🔀 Using EventSub chat backend user={self.username}")
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

    def close(self) -> None:
        """Close the bot and mark as not running."""
        logging.debug(f"🔻 Closing bot user={self.username}")
        # Note: close is sync, but since _state_lock is asyncio, we can't use it here.
        # Assuming close is called when no async operations are running.
        self.running = False
