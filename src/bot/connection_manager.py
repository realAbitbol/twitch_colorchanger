"""ConnectionManager class for TwitchColorBot - handles chat backend connections."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..chat import EventSubChatBackend

from ..constants import (
    INITIAL_BACKOFF_SECONDS,
    LISTENER_TASK_TIMEOUT_SECONDS,
    MAX_BACKOFF_SECONDS,
    RECONNECT_MAX_ATTEMPTS,
)

if TYPE_CHECKING:
    from .core import TwitchColorBot


class ConnectionManager:
    """Manages chat backend connections and reconnection logic."""

    def __init__(self, bot: TwitchColorBot) -> None:
        """Initialize the connection manager.

        Args:
            bot: The TwitchColorBot instance this manager belongs to.
        """
        self.bot = bot
        self.chat_backend: EventSubChatBackend | None = None
        self.listener_task: asyncio.Task[None] | None = None
        self._normalized_channels_cache: list[str] | None = None
        self._total_reconnect_attempts = 0

    async def initialize_connection(self) -> bool:
        """Prepare identity, choose backend, connect, and register handlers."""
        if not await self._ensure_user_id():
            return False
        await self._prime_color_state()
        logging.debug(f"🔀 Using EventSub chat backend user={self.bot.username}")
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
        if self.bot.user_id:
            return True
        user_info = await self.bot._get_user_info()
        if user_info and "id" in user_info:
            self.bot.user_id = user_info["id"]
            logging.debug(
                f"🆔 Retrieved user_id {self.bot.user_id} user={self.bot.username}"
            )
            return True
        logging.error(f"❌ Failed to retrieve user_id user={self.bot.username}")
        return False

    async def _prime_color_state(self) -> None:
        """Initialize last_color with the user's current chat color.

        Fetches the current color from Twitch API and sets it as the last known color.
        """
        current_color = await self.bot._get_current_color()
        if current_color:
            self.bot.last_color = current_color  # type: ignore
            logging.debug(
                f"🎨 Initialized with current color {current_color} user={self.bot.username}"
            )

    async def _log_scopes_if_possible(self) -> None:
        """Log the scopes of the current access token if possible.

        Validates the token with Twitch API and logs the associated scopes.
        Silently handles validation failures.
        """
        if not self.bot.context.session:
            return
        from ..api.twitch import TwitchAPI

        api = TwitchAPI(self.bot.context.session)

        async def operation():
            return await api.validate_token(self.bot.access_token)

        from ..errors.handling import handle_api_error

        try:
            validation = await handle_api_error(operation, "Token scope validation")
            raw_scopes = (
                validation.get("scopes") if isinstance(validation, dict) else None
            )
            scopes_list = (
                [str(s) for s in raw_scopes] if isinstance(raw_scopes, list) else []
            )
            logging.info(
                f"🧪 Token scopes user={self.bot.username} scopes={';'.join(scopes_list) if scopes_list else '<none>'}"
            )
        except Exception:
            logging.debug(f"🚫 Token scope validation error user={self.bot.username}")

    async def _normalize_channels_if_needed(self) -> list[str]:
        """Normalize channel names and persist if changed.

        Applies channel normalization rules and updates config if necessary.

        Returns:
            List of normalized channel names.
        """
        from ..config.model import normalize_channels_list

        normalized_channels, was_changed = normalize_channels_list(self.bot.channels)
        if was_changed:
            logging.debug(
                f"🛠️ Normalized channels old={len(self.bot.channels)} new={len(normalized_channels)} user={self.bot.username}"
            )
            self.bot.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.bot.channels = normalized_channels
        return normalized_channels

    async def _persist_normalized_channels(self) -> None:
        """Persist normalized channel list to configuration."""
        config_file = getattr(self.bot, "config_file", None)
        if config_file is None:
            return
        user_config = self.bot._build_user_config()
        # Overwrite channels explicitly
        user_config["channels"] = self.bot.channels
        from ..config.async_persistence import queue_user_update

        try:
            await queue_user_update(user_config, config_file)
        except (OSError, ValueError, RuntimeError) as e:
            logging.warning(f"Persist channels error: {str(e)}")

    async def _init_and_connect_backend(self, normalized_channels: list[str]) -> bool:
        """Initialize and connect the chat backend.

        Creates EventSub backend, sets up message handlers, connects to the first
        channel, and registers with token manager.

        Args:
            normalized_channels: List of normalized channel names.

        Returns:
            True if connection successful, False otherwise.
        """
        from ..chat import EventSubChatBackend

        if self.bot.access_token is None:
            logging.error(f"❌ Access token not available user={self.bot.username}")
            return False
        self.chat_backend = EventSubChatBackend(http_session=self.bot.context.session)
        backend = self.chat_backend
        # Route all messages through the message processor
        backend.set_message_handler(self.bot.message_processor.handle_message)
        if hasattr(backend, "set_token_invalid_callback"):
            try:
                backend.set_token_invalid_callback(
                    self.bot.token_handler.check_and_refresh_token
                )
            except Exception as e:
                logging.warning(f"Backend callback error: {str(e)}")
        connected = await backend.connect(
            self.bot.access_token,
            self.bot.username,
            normalized_channels[0],
            self.bot.user_id,
            self.bot.client_id,
            self.bot.client_secret,
        )
        if not connected:
            logging.error(f"❌ Failed to connect user={self.bot.username}")
            return False
        try:
            if self.bot.token_manager:
                await self.bot.token_manager.register_eventsub_backend(
                    self.bot.username, backend
                )
        except Exception as e:
            logging.info(f"EventSub backend registration error: {str(e)}")
        logging.debug(f"👂 Starting async message listener user={self.bot.username}")
        return True

    async def run_chat_loop(self) -> None:
        """Run primary EventSub chat backend listen task."""
        backend = self.chat_backend
        if backend is None:
            logging.error(f"⚠️ Chat backend not initialized user={self.bot.username}")
            return
        self._create_and_monitor_listener(backend)
        normalized_channels: list[str] = getattr(
            self, "_normalized_channels_cache", self.bot.channels
        )
        await self._join_additional_channels(backend, normalized_channels)

        try:
            task = self.listener_task
            if task is not None:
                await task
        except KeyboardInterrupt:
            logging.warning(f"🔻 Shutting down bot user={self.bot.username}")
        except Exception as e:  # noqa: BLE001
            await self._attempt_reconnect(e, self._listener_task_done)

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
                    f"💥 Listener task error user={self.bot.username} type={type(exc).__name__} error={str(exc)}"
                )
            except Exception as cb_e:  # noqa: BLE001
                logging.debug(
                    f"⚠️ Failed logging listener task error user={self.bot.username}: {str(cb_e)}"
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
        initial_backoff: float = INITIAL_BACKOFF_SECONDS,
        max_backoff: float = MAX_BACKOFF_SECONDS,
        max_attempts: int = RECONNECT_MAX_ATTEMPTS,
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
        self._total_reconnect_attempts += 1
        if self._total_reconnect_attempts > max_attempts:
            logging.error(
                f"❌ Max total reconnection attempts ({max_attempts}) reached, giving up user={self.bot.username}"
            )
            return
        backoff = initial_backoff
        attempts = 0
        current_error = error
        while attempts < max_attempts and self.bot.running:
            attempts += 1
            logging.warning(
                f"🔄 Listener crashed - reconnect attempt {attempts} backoff={round(backoff, 2)}s user={self.bot.username} error={str(current_error)}"
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            try:
                if not await self.initialize_connection():
                    continue
                backend2 = self.chat_backend
                if backend2 is None:
                    current_error = RuntimeError(
                        "chat backend not initialized for reconnect"
                    )
                    continue
                async with self.bot._state_lock:
                    self.listener_task = asyncio.create_task(backend2.listen())
                    self.listener_task.add_done_callback(cb)
                await self.listener_task
                self._total_reconnect_attempts = 0  # Reset on successful reconnection
                return
            except Exception as e2:  # noqa: BLE001
                current_error = e2
                continue

    async def disconnect_chat_backend(self) -> None:
        """Disconnect the chat backend if connected.

        Attempts to gracefully disconnect the EventSub backend.
        """
        backend = self.chat_backend
        if backend is not None:
            try:
                await backend.disconnect()
            except Exception as e:
                logging.warning(f"Disconnect error: {str(e)}")

    async def wait_for_listener_task(self) -> None:
        """Wait for the listener task to complete with timeout.

        Waits up to 2 seconds for the task to finish, cancels on timeout.
        """
        if self.listener_task and not self.listener_task.done():
            try:
                await asyncio.wait_for(
                    self.listener_task, timeout=LISTENER_TASK_TIMEOUT_SECONDS
                )
            except TimeoutError:
                self.listener_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.warning(f"Listener task error: {str(e)}")
