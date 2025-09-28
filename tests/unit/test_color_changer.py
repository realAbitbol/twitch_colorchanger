"""
Unit tests for ColorChanger class - focuses on cache functionality and memory leak fixes.
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.bot.color_changer import ColorChanger
from src.color.models import ColorRequestStatus


class TestColorChangerCache:
    """Test class for ColorChanger cache functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_bot = Mock()
        self.mock_bot.username = "testuser"
        self.mock_bot.user_id = "12345"
        self.mock_bot.access_token = "token"
        self.mock_bot.client_id = "client_id"
        self.mock_bot.api = Mock()
        self.changer = ColorChanger(self.mock_bot)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_cache_initialization(self):
        """Test that cache is properly initialized."""
        assert hasattr(self.changer, '_current_color_cache')
        assert isinstance(self.changer._current_color_cache, dict)
        assert self.changer._cache_ttl == 30.0
        assert self.changer._last_cleanup_time == 0.0

    @pytest.mark.asyncio
    async def test_cleanup_expired_cache_entries_removes_expired(self):
        """Test that cleanup removes expired cache entries."""
        # Setup cache with expired and fresh entries
        current_time = time.time()
        self.changer._current_color_cache = {
            "user1": {"color": "red", "timestamp": current_time - 40},  # expired
            "user2": {"color": "blue", "timestamp": current_time - 10},  # fresh
            "user3": {"color": "green", "timestamp": current_time - 35},  # expired
        }
        self.changer._last_cleanup_time = 0.0  # Force cleanup

        await self.changer._cleanup_expired_cache_entries()

        # Only fresh entry should remain
        assert "user1" not in self.changer._current_color_cache
        assert "user2" in self.changer._current_color_cache
        assert "user3" not in self.changer._current_color_cache
        assert len(self.changer._current_color_cache) == 1

    @pytest.mark.asyncio
    async def test_cleanup_not_run_too_often(self):
        """Test that cleanup doesn't run if recently executed."""
        current_time = time.time()
        self.changer._last_cleanup_time = current_time - 10  # Recent cleanup
        self.changer._current_color_cache = {
            "user1": {"color": "red", "timestamp": current_time - 40},  # expired
        }

        await self.changer._cleanup_expired_cache_entries()

        # Entry should still be there since cleanup didn't run
        assert "user1" in self.changer._current_color_cache

    @pytest.mark.asyncio
    async def test_get_current_color_uses_cache_when_fresh(self):
        """Test that _get_current_color_impl uses cache when entry is fresh."""
        current_time = time.time()
        self.changer._current_color_cache["12345"] = {
            "color": "cached_color",
            "timestamp": current_time - 10
        }

        # Mock the API call to ensure it's not called
        with patch.object(self.changer, '_make_color_request', new_callable=AsyncMock) as mock_request:
            result = await self.changer._get_current_color_impl()

        assert result == "cached_color"
        mock_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_color_fetches_when_expired(self):
        """Test that _get_current_color_impl fetches from API when cache is expired."""
        current_time = time.time()
        self.changer._current_color_cache["12345"] = {
            "color": "old_color",
            "timestamp": current_time - 40  # expired
        }

        # Mock the API call
        with patch.object(self.changer, '_make_color_request', new_callable=AsyncMock) as mock_request, \
             patch.object(self.changer, '_process_color_response') as mock_process:
            mock_request.return_value = ({"data": [{"color": "new_color"}]}, 200)
            mock_process.return_value = "new_color"

            result = await self.changer._get_current_color_impl()

        assert result == "new_color"
        # Cache should be updated
        assert self.changer._current_color_cache["12345"]["color"] == "new_color"

    @pytest.mark.asyncio
    async def test_perform_color_request_updates_cache_on_success(self):
        """Test that _perform_color_request updates cache on successful color change."""
        params = {"color": "new_color"}

        # Mock the API call
        with patch.object(self.changer, 'api') as mock_api:
            mock_api.request = AsyncMock(return_value=(None, 200, None))

            result = await self.changer._perform_color_request(params, action="test")

        assert result.status == ColorRequestStatus.SUCCESS
        # Cache should be updated
        assert self.changer._current_color_cache["12345"]["color"] == "new_color"

    @pytest.mark.asyncio
    async def test_cache_memory_bounded_with_multiple_users(self):
        """Test that cache doesn't grow unbounded with multiple users over time."""
        # Use fixed time to avoid timing issues
        fixed_time = 1000.0

        with patch('time.time', return_value=fixed_time):
            # Simulate multiple users with some expired entries
            self.changer._current_color_cache = {
                f"user{i}": {"color": f"color{i}", "timestamp": fixed_time - (i * 10)} for i in range(10)
            }
            self.changer._last_cleanup_time = 0.0  # Force cleanup

            await self.changer._cleanup_expired_cache_entries()

            # Should have removed entries older than 30 seconds
            # Entries with (fixed_time - timestamp) > 30, i.e., i*10 > 30
            # So i >= 4 (since 3*10=30 not >30)
            assert len(self.changer._current_color_cache) < 10  # Some removed
            assert "user0" in self.changer._current_color_cache  # Fresh
            assert "user3" in self.changer._current_color_cache  # 30 exactly, not expired
            assert "user4" not in self.changer._current_color_cache  # Expired

    @pytest.mark.asyncio
    async def test_cleanup_called_during_operations(self):
        """Test that cleanup is called during cache operations."""
        # Mock cleanup to track calls
        with patch.object(self.changer, '_cleanup_expired_cache_entries', new_callable=AsyncMock) as mock_cleanup:
            # Test in _get_current_color_impl
            with patch.object(self.changer, '_make_color_request', new_callable=AsyncMock) as mock_request, \
                 patch.object(self.changer, '_process_color_response') as mock_process:
                mock_request.return_value = ({"data": [{"color": "color"}]}, 200)
                mock_process.return_value = "color"

                await self.changer._get_current_color_impl()

            # Cleanup should have been called
            mock_cleanup.assert_called()

            # Reset mock
            mock_cleanup.reset_mock()

            # Test in _perform_color_request
            with patch.object(self.changer, 'api') as mock_api:
                mock_api.request = AsyncMock(return_value=(None, 200, None))

                await self.changer._perform_color_request({"color": "test"}, action="test")

            # Cleanup should have been called again
            mock_cleanup.assert_called()
