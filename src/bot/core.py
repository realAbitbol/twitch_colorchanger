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
from ..color import ColorChangeService
from ..config.async_persistence import (
    flush_pending_updates,
)
from ..constants import (
    BOT_STOP_DELAY_SECONDS,
)
from .color_changer import ColorChanger
from .connection_manager import ConnectionManager
from .message_processor import MessageProcessor
from .token_handler import TokenHandler


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
        self.last_color: str | None = None

        # Lazy/optional services
        self._color_service: ColorChangeService | None = None
        self._last_color_change_payload: dict[str, Any] | None = None

        # Initialize composed components
        self.connection_manager: ConnectionManager = ConnectionManager(self)
        self.message_processor: MessageProcessor = MessageProcessor(self)
        self.color_changer: ColorChanger = ColorChanger(self)
        self.token_handler: TokenHandler = TokenHandler(self)

    async def start(self) -> None:
        """Start the bot's main execution loop.

        Initializes token management, establishes chat connection, and begins
        listening for messages. Handles setup failures gracefully by stopping
        early if critical components cannot be initialized.
        """
        logging.info(f"▶️ Starting bot user={self.username}")
        async with self._state_lock:
            self.running = True
        if not self.token_handler.setup_token_manager():
            async with self._state_lock:
                self.running = False
            return
        await self.token_handler.handle_initial_token_refresh()
        if not await self.connection_manager.initialize_connection():
            async with self._state_lock:
                self.running = False
            return
        await self.connection_manager.run_chat_loop()

    async def stop(self) -> None:
        """Stop the bot and clean up resources.

        Disconnects chat backend, waits for listener task to finish, flushes
        pending config updates, and sets running flag to False.
        """
        logging.warning(f"🛑 Stopping bot user={self.username}")
        async with self._state_lock:
            self.running = False
        await self.connection_manager.disconnect_chat_backend()
        await self.connection_manager.wait_for_listener_task()
        if self.config_file:
            try:
                await flush_pending_updates(self.config_file)
            except Exception as e:
                logging.debug(f"Config flush error: {str(e)}")
        self.running = False
        await asyncio.sleep(BOT_STOP_DELAY_SECONDS)

    async def _get_user_info(self) -> dict[str, Any] | None:
        """Fetch user information from Twitch API.

        Returns:
            User info dict or None if failed.
        """
        return await self.color_changer._get_user_info()

    async def _get_current_color(self) -> str | None:
        """Fetch the user's current chat color from Twitch API.

        Returns:
            Color string or None if failed.
        """
        return await self.color_changer._get_current_color()

    def _build_user_config(self) -> dict[str, Any]:
        """Build user configuration dict from current instance state.

        Returns:
            Dict containing all user configuration fields.
        """
        return self.token_handler._build_user_config()

    # Delegate methods to composed objects for backward compatibility
    async def handle_message(
        self,
        sender: str,
        channel: str,
        message: str,
    ) -> None:
        """Handle incoming chat messages."""
        try:
            await self.message_processor.handle_message(sender, channel, message)
        except Exception as e:
            logging.error(f"💥 Message processing error: {str(e)}")

    async def _change_color(self, color: str | None = None) -> None:
        """Change the bot's color."""
        await self.color_changer._change_color(color)

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        """Check and refresh the access token if needed."""
        return await self.token_handler.check_and_refresh_token(force)

    def _listener_task_done(self, task: asyncio.Task[None]) -> None:
        """Callback for listener task completion."""
        self.connection_manager._listener_task_done(task)

    async def _join_additional_channels(
        self, backend: EventSubChatBackend, normalized_channels: list[str]
    ) -> None:
        """Join additional channels beyond the first."""
        await self.connection_manager._join_additional_channels(
            backend, normalized_channels
        )

    async def _attempt_reconnect(
        self,
        error: Exception,
        cb: Callable[[asyncio.Task[None]], None],
        *,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        max_attempts: int = 5,
    ) -> None:
        """Attempt to reconnect chat backend with exponential backoff."""
        if not self.running:
            return
        await self.connection_manager._attempt_reconnect(
            error,
            cb,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            max_attempts=max_attempts,
        )

    async def _initialize_connection(self) -> bool:
        """Initialize the chat backend connection."""
        return await self.connection_manager.initialize_connection()

    async def _ensure_user_id(self) -> bool:
        """Ensure user_id is available."""
        return await self.color_changer._ensure_user_id()

    async def _prime_color_state(self) -> None:
        """Initialize last_color with the user's current chat color."""
        await self.color_changer._prime_color_state()

    async def _log_scopes_if_possible(self) -> None:
        """Log the scopes of the current access token if possible."""
        await self.token_handler.log_scopes_if_possible()

    async def _normalize_channels_if_needed(self) -> list[str]:
        """Normalize channel names and persist if changed."""
        return await self.token_handler.normalize_channels_if_needed()

    async def _init_and_connect_backend(self, channels: list[str]) -> None:
        """Initialize and connect the chat backend."""
        await self.connection_manager._init_and_connect_backend(channels)

    async def _disconnect_chat_backend(self) -> None:
        """Disconnect the chat backend."""
        await self.connection_manager.disconnect_chat_backend()

    async def _wait_for_listener_task(self) -> None:
        """Wait for the listener task to complete."""
        await self.connection_manager.wait_for_listener_task()

    def _setup_token_manager(self) -> bool:
        """Set up the token manager."""
        return self.token_handler.setup_token_manager()

    async def _handle_initial_token_refresh(self) -> None:
        """Handle initial token refresh."""
        await self.token_handler.handle_initial_token_refresh()

    async def _run_chat_loop(self) -> None:
        """Run the chat loop."""
        await self.connection_manager.run_chat_loop()

    def close(self) -> None:
        """Close the bot and mark as not running."""
        logging.debug(f"🔻 Closing bot user={self.username}")
        # Note: close is sync, but since _state_lock is asyncio, we can't use it here.
        # Assuming close is called when no async operations are running.
        self.running = False
