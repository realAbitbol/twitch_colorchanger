"""
Unit tests for ClientCache.
"""

from unittest.mock import Mock

import pytest

from src.auth_token.client_cache import ClientCache


class TestClientCache:
    """Test class for ClientCache functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_manager = Mock()
        self.cache = ClientCache(self.mock_manager)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_get_client_creates_new_client(self):
        """Test get_client creates new TokenClient when not cached."""
        # Arrange
        self.mock_manager.http_session = Mock()

        # Act
        client = await self.cache.get_client("client_id_123", "client_secret_456")

        # Assert
        assert client is not None
        assert client.client_id == "client_id_123"
        assert client.client_secret == "client_secret_456"
        assert client.session == self.mock_manager.http_session

    @pytest.mark.asyncio
    async def test_get_client_returns_cached_client(self):
        """Test get_client returns cached TokenClient for same credentials."""
        # Arrange
        self.mock_manager.http_session = Mock()

        # Act - First call
        client1 = await self.cache.get_client("client_id_123", "client_secret_456")

        # Act - Second call with same credentials
        client2 = await self.cache.get_client("client_id_123", "client_secret_456")

        # Assert
        assert client1 is client2  # Same instance returned
        assert client1.client_id == "client_id_123"
        assert client1.client_secret == "client_secret_456"

    @pytest.mark.asyncio
    async def test_get_client_creates_different_clients_for_different_credentials(self):
        """Test get_client creates different clients for different credentials."""
        # Arrange
        self.mock_manager.http_session = Mock()

        # Act
        client1 = await self.cache.get_client("client_id_123", "client_secret_456")
        client2 = await self.cache.get_client("client_id_789", "client_secret_012")

        # Assert
        assert client1 is not client2
        assert client1.client_id == "client_id_123"
        assert client1.client_secret == "client_secret_456"
        assert client2.client_id == "client_id_789"
        assert client2.client_secret == "client_secret_012"

    @pytest.mark.asyncio
    async def test_get_client_caches_multiple_clients(self):
        """Test get_client properly caches multiple different clients."""
        # Arrange
        self.mock_manager.http_session = Mock()

        # Act
        client1a = await self.cache.get_client("client1", "secret1")
        client2a = await self.cache.get_client("client2", "secret2")
        client1b = await self.cache.get_client("client1", "secret1")
        client2b = await self.cache.get_client("client2", "secret2")

        # Assert
        assert client1a is client1b
        assert client2a is client2b
        assert client1a is not client2a

        # Verify cache has 2 entries
        assert len(self.cache._client_cache) == 2
