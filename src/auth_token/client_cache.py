"""TokenClient caching."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .client import TokenClient

if TYPE_CHECKING:
    from .manager import TokenManager


class ClientCache:
    """Manages TokenClient caching and retrieval."""

    def __init__(self, manager: TokenManager) -> None:
        self.manager = manager
        self._client_cache_lock = asyncio.Lock()
        self._client_cache: dict[tuple[str, str], TokenClient] = {}

    async def get_client(self, client_id: str, client_secret: str) -> TokenClient:
        """Retrieve or create a TokenClient for the given credentials.

        Uses caching to avoid creating multiple clients for the same credentials.

        Args:
            client_id: Twitch client ID.
            client_secret: Twitch client secret.

        Returns:
            TokenClient instance for the credentials.
        """
        async with self._client_cache_lock:
            key = (client_id, client_secret)
            cli = self._client_cache.get(key)
            if cli:
                return cli
            cli = TokenClient(client_id, client_secret, self.manager.http_session)
            self._client_cache[key] = cli
            return cli
