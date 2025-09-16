from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from ..api.twitch import TwitchAPI
from ..chat.cache_manager import CacheManager
from ..chat.channel_resolver import ChannelResolver
from ..chat.message_processor import MessageProcessor
from ..chat.subscription_manager import SubscriptionManager
from ..chat.token_manager import TokenManager
from ..chat.websocket_connection_manager import WebSocketConnectionManager
from ..constants import (
    EVENTSUB_SUB_CHECK_INTERVAL_SECONDS,
)

MessageHandler = Callable[[str, str, str], Any]


class EventSubChatBackend:
    """EventSub WebSocket chat backend for Twitch.

    This refactored class acts as an orchestrator coordinating all modular components
    (WebSocketConnectionManager, SubscriptionManager, MessageProcessor, ChannelResolver,
    TokenManager, CacheManager) through dependency injection. It maintains backward
    compatibility while simplifying the public API and managing component lifecycle.

    Attributes:
        _session (aiohttp.ClientSession): HTTP session for API calls.
        _api (TwitchAPI): Twitch API client instance.
        _ws_manager (WebSocketConnectionManager): Manages WebSocket connections.
        _sub_manager (SubscriptionManager): Manages EventSub subscriptions.
        _msg_processor (MessageProcessor): Processes incoming messages.
        _channel_resolver (ChannelResolver): Resolves user IDs with caching.
        _token_manager (TokenManager): Handles token validation and refresh.
        _cache_manager (CacheManager): Handles file-based caching.
        _message_handler (MessageHandler | None): Callback for chat messages.
        _color_handler (MessageHandler | None): Callback for color commands.
        _token (str | None): OAuth access token.
        _client_id (str | None): Twitch client ID.
        _username (str | None): Bot username.
        _user_id (str | None): Bot user ID.
        _primary_channel (str | None): Primary channel login.
        _channels (list[str]): List of joined channels.
        _stop_event (asyncio.Event): Event to signal shutdown.
        _reconnect_requested (bool): Flag for reconnect request.
        _last_activity (float): Timestamp of last WebSocket activity.
        _next_sub_check (float): Next subscription verification time.
        _stale_threshold (float): Threshold for stale connection.
    """

    def __init__(
        self,
        http_session: aiohttp.ClientSession | None = None,
        ws_manager: WebSocketConnectionManager | None = None,
        sub_manager: SubscriptionManager | None = None,
        msg_processor: MessageProcessor | None = None,
        channel_resolver: ChannelResolver | None = None,
        token_manager: TokenManager | None = None,
        cache_manager: CacheManager | None = None,
    ) -> None:
        """Initialize the EventSub chat backend with dependency injection.

        Args:
            http_session (aiohttp.ClientSession | None): Optional HTTP session.
            ws_manager (WebSocketConnectionManager | None): WebSocket manager instance.
            sub_manager (SubscriptionManager | None): Subscription manager instance.
            msg_processor (MessageProcessor | None): Message processor instance.
            channel_resolver (ChannelResolver | None): Channel resolver instance.
            token_manager (TokenManager | None): Token manager instance.
            cache_manager (CacheManager | None): Cache manager instance.
        """
        self._session = http_session or aiohttp.ClientSession()
        self._api = TwitchAPI(self._session)

        # Injected components (will be created if not provided)
        self._ws_manager = ws_manager
        self._sub_manager = sub_manager
        self._msg_processor = msg_processor
        self._channel_resolver = channel_resolver
        self._token_manager = token_manager
        self._cache_manager = cache_manager

        # Handlers
        self._message_handler: MessageHandler | None = None
        self._color_handler: MessageHandler | None = None

        # Credentials and identity
        self._token: str | None = None
        self._client_id: str | None = None
        self._username: str | None = None
        self._user_id: str | None = None
        self._primary_channel: str | None = None

        # Channel bookkeeping
        self._channels: list[str] = []

        # Async runtime primitives
        self._stop_event = asyncio.Event()
        self._reconnect_requested = False

        # Activity tracking
        self._last_activity = time.monotonic()
        self._next_sub_check = self._last_activity + EVENTSUB_SUB_CHECK_INTERVAL_SECONDS
        self._stale_threshold = 60.0  # 1 minute default

        # Backward compatibility attributes
        self._scopes: set[str] = set()

    async def __aenter__(self) -> EventSubChatBackend:
        """Async context manager entry."""
        await self._initialize_components()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        await self._cleanup_components()

    async def _initialize_components(self) -> None:
        """Initialize all components if not injected."""
        if self._cache_manager is None:
            from pathlib import Path

            cache_path = Path("broadcaster_ids.cache.json").resolve()
            self._cache_manager = CacheManager(str(cache_path))

        if self._channel_resolver is None:
            self._channel_resolver = ChannelResolver(self._api, self._cache_manager)

        if self._token_manager is None and self._client_id:
            self._token_manager = TokenManager(
                username=self._username or "",
                client_id=self._client_id,
                client_secret="",  # Will be set later if needed
                http_session=self._session,
            )
            self._token_manager.set_invalid_callback(self._on_token_invalid)

        if self._ws_manager is None and self._token and self._client_id:
            self._ws_manager = WebSocketConnectionManager(
                session=self._session,
                token=self._token,
                client_id=self._client_id,
            )

        if self._sub_manager is None and self._ws_manager:
            self._sub_manager = SubscriptionManager(
                api=self._api,
                session_id=self._ws_manager.session_id or "",
                token=self._token or "",
                client_id=self._client_id or "",
            )

        if self._msg_processor is None:
            self._msg_processor = MessageProcessor(
                message_handler=self._message_handler or (lambda *args: None),
                color_handler=self._color_handler or (lambda *args: None),
            )

    async def _cleanup_components(self) -> None:
        """Cleanup all components."""
        if self._ws_manager:
            await self._ws_manager.disconnect()
        if self._sub_manager:
            await self._sub_manager.unsubscribe_all()
        if self._cache_manager:
            pass  # CacheManager handles its own cleanup
        if self._session and not self._session.closed:
            await self._session.close()

    def set_token_invalid_callback(self, callback) -> None:
        """Sets the callback for token invalidation events.

        Args:
            callback: Function to call when the token becomes invalid.
        """
        if self._token_manager:
            self._token_manager.set_invalid_callback(callback)

    async def connect(
        self,
        token: str,
        username: str,
        primary_channel: str,
        user_id: str | None,
        client_id: str | None,
        client_secret: str | None = None,
    ) -> bool:
        """Connect to Twitch EventSub WebSocket and subscribe to chat messages.

        Args:
            token (str): OAuth access token.
            username (str): Bot username.
            primary_channel (str): Primary channel to join.
            user_id (str | None): Bot user ID, if known.
            client_id (str | None): Twitch client ID.
            client_secret (str | None): Client secret (currently unused).

        Returns:
            bool: True if connection and subscription successful, False otherwise.
        """
        try:
            # Set credentials
            self._token = token
            self._username = username.lower()
            self._user_id = user_id
            self._primary_channel = primary_channel.lstrip("#").lower()
            self._client_id = client_id
            self._channels = [self._primary_channel]

            # Initialize components
            await self._initialize_components()

            # Validate token and scopes
            if self._token_manager:
                if not await self._token_manager.validate_token(token):
                    return False
                self._scopes = self._token_manager.get_scopes()

            # Resolve channels
            if self._channel_resolver:
                user_ids = await self._channel_resolver.resolve_user_ids(
                    [self._primary_channel], token, client_id or ""
                )
                if self._primary_channel not in user_ids:
                    return False

            # Connect WebSocket
            if self._ws_manager:
                await self._ws_manager.connect()
                if self._sub_manager:
                    self._sub_manager.update_session_id(
                        self._ws_manager.session_id or ""
                    )

            # Subscribe to primary channel
            if self._sub_manager:
                channel_id = user_ids.get(self._primary_channel)
                if channel_id:
                    success = await self._sub_manager.subscribe_channel_chat(
                        channel_id, self._user_id or ""
                    )
                    if not success:
                        return False

            return True

        except Exception as e:
            logging.error(f"EventSub connect failed: {str(e)}")
            return False

    async def listen(self) -> None:
        """Listen for WebSocket messages and handle them."""
        if not self._ws_manager or not self._ws_manager.is_connected:
            return

        while not self._stop_event.is_set():
            now = time.monotonic()
            await self._maybe_verify_subs(now)

            try:
                msg = await self._ws_manager.receive_message()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._last_activity = time.monotonic()
                    if self._msg_processor:
                        await self._msg_processor.process_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logging.info("WebSocket abnormal end")
                    await self._handle_reconnect()
                    break
            except Exception as e:
                logging.warning(f"Listen loop error: {str(e)}")
                await self._handle_reconnect()
                break

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket and cleanup resources."""
        self._stop_event.set()
        await self._cleanup_components()

    def update_access_token(self, new_token: str | None) -> None:
        """Updates the access token after external refresh.

        Args:
            new_token (str | None): The new access token.
        """
        if not new_token:
            return
        self._token = new_token
        if self._token_manager:
            asyncio.create_task(self._token_manager.validate_token(new_token))

    async def join_channel(self, channel: str) -> bool:
        """Joins a channel and subscribes to its chat messages.

        Args:
            channel (str): Channel name to join.

        Returns:
            bool: True if joined successfully, False otherwise.
        """
        channel_l = channel.lstrip("#").lower()
        if channel_l in self._channels:
            return True

        try:
            # Resolve channel ID
            if self._channel_resolver:
                user_ids = await self._channel_resolver.resolve_user_ids(
                    [channel_l], self._token or "", self._client_id or ""
                )
                channel_id = user_ids.get(channel_l)
                if not channel_id:
                    return False

                # Subscribe
                if self._sub_manager:
                    success = await self._sub_manager.subscribe_channel_chat(
                        channel_id, self._user_id or ""
                    )
                    if success:
                        self._channels.append(channel_l)
                        return True

            return False

        except Exception as e:
            logging.warning(f"Join channel failed: {str(e)}")
            return False

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Sets the handler for incoming chat messages.

        Args:
            handler (MessageHandler): Function to handle messages.
        """
        self._message_handler = handler
        if self._msg_processor:
            self._msg_processor.message_handler = handler

    def set_color_handler(self, handler: MessageHandler) -> None:
        """Sets the handler for color/command messages.

        Args:
            handler (MessageHandler): Function to handle color messages.
        """
        self._color_handler = handler
        if self._msg_processor:
            self._msg_processor.color_handler = handler

    def update_token(self, new_token: str) -> None:
        """Updates the access token.

        Args:
            new_token (str): The new access token.
        """
        self.update_access_token(new_token)

    def get_scopes(self) -> set[str]:
        """Get the currently recorded OAuth scopes.

        Returns:
            set[str]: Set of recorded scopes.
        """
        return self._scopes.copy()

    def get_channels(self) -> list[str]:
        """Get list of joined channels.

        Returns:
            list[str]: List of channel names.
        """
        return self._channels.copy()

    async def leave_channel(self, channel: str) -> bool:
        """Leave a channel and unsubscribe from its chat messages.

        Args:
            channel (str): Channel name to leave.

        Returns:
            bool: True if left successfully, False otherwise.
        """
        channel_l = channel.lstrip("#").lower()
        if channel_l not in self._channels:
            return True

        try:
            # For now, just remove from channels list
            # Full unsubscription would require tracking subscription IDs
            self._channels.remove(channel_l)
            return True
        except Exception as e:
            logging.warning(f"Leave channel failed: {str(e)}")
            return False

    def is_connected(self) -> bool:
        """Check if WebSocket is connected.

        Returns:
            bool: True if connected, False otherwise.
        """
        return self._ws_manager is not None and self._ws_manager.is_connected

    def get_session_id(self) -> str | None:
        """Get the current EventSub session ID.

        Returns:
            str | None: Session ID if connected, None otherwise.
        """
        return self._ws_manager.session_id if self._ws_manager else None

    def get_user_id(self) -> str | None:
        """Get the bot's user ID.

        Returns:
            str | None: User ID if set, None otherwise.
        """
        return self._user_id

    def get_username(self) -> str | None:
        """Get the bot's username.

        Returns:
            str | None: Username if set, None otherwise.
        """
        return self._username

    def get_primary_channel(self) -> str | None:
        """Get the primary channel.

        Returns:
            str | None: Primary channel if set, None otherwise.
        """
        return self._primary_channel

    async def _maybe_verify_subs(self, now: float) -> None:
        """Conditionally verifies subscriptions based on timing.

        Args:
            now (float): Current monotonic time.
        """
        if now < self._next_sub_check:
            return
        try:
            if self._sub_manager:
                active_channels = await self._sub_manager.verify_subscriptions()
                # Update channels list
                self._channels = [ch for ch in self._channels if ch in active_channels]
        except Exception as e:
            logging.info(f"Subscription check error: {str(e)}")
        self._next_sub_check = now + EVENTSUB_SUB_CHECK_INTERVAL_SECONDS

    async def _handle_reconnect(self) -> None:
        """Handle reconnection logic."""
        if self._ws_manager:
            await self._ws_manager.reconnect()
            # Re-subscribe to all channels
            if self._sub_manager:
                for channel in self._channels:
                    # Resolve and subscribe again
                    if self._channel_resolver:
                        user_ids = await self._channel_resolver.resolve_user_ids(
                            [channel], self._token or "", self._client_id or ""
                        )
                        channel_id = user_ids.get(channel)
                        if channel_id:
                            await self._sub_manager.subscribe_channel_chat(
                                channel_id, self._user_id or ""
                            )

    async def _on_token_invalid(self) -> None:
        """Callback invoked when token is detected as invalid."""
        logging.error(f"Token invalidated for user {self._username}")
        # Could trigger reconnect or other recovery logic here
