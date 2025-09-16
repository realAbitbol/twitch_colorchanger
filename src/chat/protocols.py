"""Protocol definitions for chat components.

This module defines Protocol interfaces using typing.Protocol for all chat components,
enabling loose coupling and better type safety. Each protocol defines the essential
methods and properties that components must implement.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Protocol

import aiohttp


class WebSocketConnectionManagerProtocol(Protocol):
    """Protocol for WebSocket connection management."""

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected and active."""
        ...

    async def connect(self) -> None:
        """Establish WebSocket connection and perform handshake."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources."""
        ...

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send JSON data over WebSocket."""
        ...

    async def receive_message(self) -> aiohttp.WSMessage:
        """Receive a WebSocket message."""
        ...

    async def reconnect(self) -> None:
        """Request reconnection with backoff."""
        ...

    async def __aenter__(self) -> WebSocketConnectionManagerProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...


class SubscriptionManagerProtocol(Protocol):
    """Protocol for managing EventSub subscriptions."""

    async def subscribe_channel_chat(self, channel_id: str, user_id: str) -> bool:
        """Subscribe to chat messages for a specific channel."""
        ...

    async def verify_subscriptions(self) -> list[str]:
        """Verify active subscriptions and return list of active channel IDs."""
        ...

    async def unsubscribe_all(self) -> None:
        """Unsubscribe from all active subscriptions."""
        ...

    def get_active_channel_ids(self) -> list[str]:
        """Get list of channel IDs with active subscriptions."""
        ...

    def update_session_id(self, new_session_id: str) -> None:
        """Update the session ID for new subscriptions."""
        ...

    async def __aenter__(self) -> SubscriptionManagerProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...


class MessageProcessorProtocol(Protocol):
    """Protocol for processing EventSub WebSocket messages."""

    async def process_message(self, raw_message: str) -> None:
        """Process a raw WebSocket message from EventSub."""
        ...

    async def __aenter__(self) -> MessageProcessorProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...


class ChannelResolverProtocol(Protocol):
    """Protocol for resolving Twitch user IDs with caching."""

    async def resolve_user_ids(
        self,
        logins: list[str],
        access_token: str,
        client_id: str,
    ) -> dict[str, str]:
        """Resolve a list of Twitch login names to user IDs."""
        ...

    async def invalidate_cache(self, login: str) -> None:
        """Invalidate the cache entry for a specific login."""
        ...

    async def clear_cache(self) -> None:
        """Clear all cached user ID mappings."""
        ...

    async def __aenter__(self) -> ChannelResolverProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...


class TokenManagerProtocol(Protocol):
    """Protocol for managing OAuth tokens for EventSub operations."""

    async def validate_token(self, access_token: str) -> bool:
        """Validate the access token and record its scopes."""
        ...

    async def refresh_token(self, force_refresh: bool = False) -> bool:
        """Coordinate token refresh operation."""
        ...

    def check_scopes(self) -> bool:
        """Validate that all required scopes are present."""
        ...

    def set_invalid_callback(
        self, callback: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for token invalidation events."""
        ...

    async def handle_401_error(self) -> None:
        """Handle a 401 Unauthorized error with threshold-based invalidation."""
        ...

    def get_scopes(self) -> set[str]:
        """Get the currently recorded OAuth scopes."""
        ...

    async def is_token_valid(self) -> bool:
        """Check if the current token is valid and has required scopes."""
        ...

    def reset_401_counter(self) -> None:
        """Reset the consecutive 401 error counter."""
        ...

    async def ensure_valid_token(self) -> str | None:
        """Ensure the token is valid and return it."""
        ...

    async def __aenter__(self) -> TokenManagerProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...


class CacheManagerProtocol(Protocol):
    """Protocol for asynchronous file-based caching."""

    async def get(self, key: str) -> Any:
        """Retrieve a value from the cache."""
        ...

    async def set(self, key: str, value: Any) -> None:
        """Store a value in the cache."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        ...

    async def clear(self) -> None:
        """Clear all data from the cache."""
        ...

    async def contains(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        ...

    async def keys(self) -> list[str]:
        """Get all keys in the cache."""
        ...

    async def __aenter__(self) -> CacheManagerProtocol:
        """Async context manager entry."""
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        ...
