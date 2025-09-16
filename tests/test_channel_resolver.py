"""Unit tests for ChannelResolver."""

from unittest.mock import AsyncMock

import pytest

from src.api.twitch import TwitchAPI
from src.chat.cache_manager import CacheManager
from src.chat.channel_resolver import ChannelResolver
from src.errors.eventsub import CacheError, EventSubError


class TestChannelResolver:
    """Test suite for ChannelResolver."""

    @pytest.fixture
    async def mock_twitch_api(self):
        """Create a mock TwitchAPI."""
        api = AsyncMock(spec=TwitchAPI)
        return api

    @pytest.fixture
    async def mock_cache_manager(self):
        """Create a mock CacheManager."""
        cache = AsyncMock(spec=CacheManager)
        return cache

    @pytest.fixture
    async def channel_resolver(self, mock_twitch_api, mock_cache_manager):
        """Create a ChannelResolver with mocked dependencies."""
        return ChannelResolver(mock_twitch_api, mock_cache_manager)

    async def test_init_valid_dependencies(self, mock_twitch_api, mock_cache_manager):
        """Test initialization with valid dependencies."""
        resolver = ChannelResolver(mock_twitch_api, mock_cache_manager)
        assert resolver._twitch_api == mock_twitch_api
        assert resolver._cache_manager == mock_cache_manager
        assert resolver._max_concurrent_batches == 3

    async def test_init_custom_concurrency(self, mock_twitch_api, mock_cache_manager):
        """Test initialization with custom concurrency limit."""
        resolver = ChannelResolver(mock_twitch_api, mock_cache_manager, max_concurrent_batches=5)
        assert resolver._max_concurrent_batches == 5

    async def test_init_none_twitch_api_raises(self, mock_cache_manager):
        """Test initialization with None twitch_api raises ValueError."""
        with pytest.raises(ValueError, match="twitch_api cannot be None"):
            ChannelResolver(None, mock_cache_manager)

    async def test_init_none_cache_manager_raises(self, mock_twitch_api):
        """Test initialization with None cache_manager raises ValueError."""
        with pytest.raises(ValueError, match="cache_manager cannot be None"):
            ChannelResolver(mock_twitch_api, None)

    async def test_resolve_user_ids_empty_list(self, channel_resolver):
        """Test resolving empty list returns empty dict."""
        result = await channel_resolver.resolve_user_ids([], "token", "client_id")
        assert result == {}

    async def test_resolve_user_ids_all_cached(self, channel_resolver, mock_cache_manager):
        """Test resolving when all logins are cached."""
        mock_cache_manager.get.side_effect = lambda key: {
            "alice": "11111",
            "bob": "22222"
        }.get(key)

        result = await channel_resolver.resolve_user_ids(
            ["Alice", "Bob"], "token", "client_id"
        )

        assert result == {"alice": "11111", "bob": "22222"}
        # Should not call API
        channel_resolver._twitch_api.get_users_by_login.assert_not_called()

    async def test_resolve_user_ids_all_uncached(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test resolving when all logins are uncached."""
        # Cache returns None
        mock_cache_manager.get.return_value = None
        # API returns results
        mock_twitch_api.get_users_by_login.return_value = {
            "alice": "11111",
            "bob": "22222"
        }

        result = await channel_resolver.resolve_user_ids(
            ["Alice", "Bob"], "token", "client_id"
        )

        assert result == {"alice": "11111", "bob": "22222"}
        mock_twitch_api.get_users_by_login.assert_called_once_with(
            access_token="token",
            client_id="client_id",
            logins=["Alice", "Bob"]
        )
        # Should cache results
        mock_cache_manager.set.assert_any_call("alice", "11111")
        mock_cache_manager.set.assert_any_call("bob", "22222")

    async def test_resolve_user_ids_mixed_cached_uncached(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test resolving with mix of cached and uncached logins."""
        # Alice cached, Bob not
        mock_cache_manager.get.side_effect = lambda key: {
            "alice": "11111"
        }.get(key)

        mock_twitch_api.get_users_by_login.return_value = {"bob": "22222"}

        result = await channel_resolver.resolve_user_ids(
            ["Alice", "Bob"], "token", "client_id"
        )

        assert result == {"alice": "11111", "bob": "22222"}
        mock_twitch_api.get_users_by_login.assert_called_once_with(
            access_token="token",
            client_id="client_id",
            logins=["Bob"]
        )

    async def test_resolve_user_ids_deduplicates_logins(self, channel_resolver, mock_cache_manager):
        """Test that duplicate logins are deduplicated."""
        mock_cache_manager.get.side_effect = lambda key: {
            "alice": "11111"
        }.get(key)

        result = await channel_resolver.resolve_user_ids(
            ["Alice", "alice", "ALICE"], "token", "client_id"
        )

        assert result == {"alice": "11111"}
        # Should only check cache once
        assert mock_cache_manager.get.call_count == 1

    async def test_resolve_user_ids_cache_failure_falls_back_to_api(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test that cache read failure falls back to API."""
        mock_cache_manager.get.side_effect = CacheError("Cache read failed")
        mock_twitch_api.get_users_by_login.return_value = {"alice": "11111"}

        result = await channel_resolver.resolve_user_ids(
            ["Alice"], "token", "client_id"
        )

        assert result == {"alice": "11111"}

    async def test_resolve_user_ids_api_failure_raises(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test that API failure raises EventSubError."""
        mock_cache_manager.get.return_value = None
        mock_twitch_api.get_users_by_login.side_effect = Exception("API failed")

        with pytest.raises(EventSubError) as exc_info:
            await channel_resolver.resolve_user_ids(
                ["Alice"], "token", "client_id"
            )
        assert "All 1 API batches failed to resolve 1 logins" in str(exc_info.value)

    async def test_resolve_user_ids_cache_write_failure_logs_warning(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test that cache write failure logs warning but doesn't fail."""
        mock_cache_manager.get.return_value = None
        mock_twitch_api.get_users_by_login.return_value = {"alice": "11111"}
        mock_cache_manager.set.side_effect = CacheError("Cache write failed")

        result = await channel_resolver.resolve_user_ids(
            ["Alice"], "token", "client_id"
        )

        assert result == {"alice": "11111"}
        # Should still return results despite cache failure

    async def test_resolve_user_ids_concurrent_batches(self, channel_resolver, mock_twitch_api, mock_cache_manager):
        """Test concurrent processing of multiple batches."""
        # Simulate many logins requiring multiple batches
        logins = [f"user{i}" for i in range(250)]  # More than 100*2
        mock_cache_manager.get.return_value = None

        # Mock API to return different results for different batches
        mock_twitch_api.get_users_by_login.side_effect = [
            {f"user{i}": f"id{i}" for i in range(100)},
            {f"user{i}": f"id{i}" for i in range(100, 200)},
            {f"user{i}": f"id{i}" for i in range(200, 250)},
        ]

        result = await channel_resolver.resolve_user_ids(
            logins, "token", "client_id"
        )

        assert len(result) == 250
        assert mock_twitch_api.get_users_by_login.call_count == 3  # 3 batches

    async def test_invalidate_cache_success(self, channel_resolver, mock_cache_manager):
        """Test invalidating cache entry."""
        await channel_resolver.invalidate_cache("alice")

        mock_cache_manager.delete.assert_called_once_with("alice")

    async def test_invalidate_cache_failure_raises(self, channel_resolver, mock_cache_manager):
        """Test that cache delete failure raises CacheError."""
        mock_cache_manager.delete.side_effect = CacheError("Delete failed")

        with pytest.raises(CacheError) as exc_info:
            await channel_resolver.invalidate_cache("alice")
        assert "Failed to invalidate cache" in str(exc_info.value)

    async def test_clear_cache_success(self, channel_resolver, mock_cache_manager):
        """Test clearing all cache."""
        await channel_resolver.clear_cache()

        mock_cache_manager.clear.assert_called_once()

    async def test_clear_cache_failure_raises(self, channel_resolver, mock_cache_manager):
        """Test that cache clear failure raises CacheError."""
        mock_cache_manager.clear.side_effect = CacheError("Clear failed")

        with pytest.raises(CacheError) as exc_info:
            await channel_resolver.clear_cache()
        assert "Failed to clear cache" in str(exc_info.value)
