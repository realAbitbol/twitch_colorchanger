from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..chat.cache_manager import CacheManager
from ..chat.channel_resolver import ChannelResolver
from ..chat.message_processor import MessageProcessor
from ..chat.token_manager import TokenManager
from ..chat.websocket_connection_manager import WebSocketConnectionManager

if TYPE_CHECKING:
    from .eventsub_backend import EventSubChatBackend


class ConnectionCoordinator:
    """Coordinates initialization of all component dependencies."""

    def __init__(self, backend: EventSubChatBackend) -> None:
        """Initialize components for the backend."""
        self.backend = backend
        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize all components if not injected."""
        if self.backend._cache_manager is None:
            # Check for environment variable
            env_cache_path = os.getenv("TWITCH_BROADCASTER_CACHE")
            if env_cache_path:
                cache_path = Path(env_cache_path)
                logging.debug(
                    f"Using cache path from TWITCH_BROADCASTER_CACHE: {cache_path}"
                )
            else:
                cache_path = Path("broadcaster_ids.cache.json").resolve()
                logging.debug(f"Using default cache path: {cache_path}")

            self.backend._cache_manager = CacheManager(str(cache_path))

        if self.backend._channel_resolver is None:
            self.backend._channel_resolver = ChannelResolver(self.backend._api, self.backend._cache_manager)

        # SubscriptionManager will be created after WebSocket connection
        # when session_id is available

        if self.backend._msg_processor is None:
            self.backend._msg_processor = MessageProcessor(
                message_handler=self.backend._message_handler or (lambda *args: None),
                color_handler=self.backend._color_handler or (lambda *args: None),
            )

    def initialize_credential_components(self, token: str | None, client_id: str | None, client_secret: str | None, username: str | None) -> None:
        """Initialize components that depend on credentials."""
        if self.backend._token_manager is None and client_id and client_secret:
            self.backend._token_manager = TokenManager(
                username=username or "",
                client_id=client_id,
                client_secret=client_secret,
                http_session=self.backend._session,
            )
            self.backend._token_manager.set_invalid_callback(self.backend._on_token_invalid)

        if self.backend._ws_manager is None and token and client_id:
            self.backend._ws_manager = WebSocketConnectionManager(
                session=self.backend._session,
                token=token,
                client_id=client_id,
            )
