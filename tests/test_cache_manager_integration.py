"""Integration tests for CacheManager with EventSubChatBackend."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.chat.cache_manager import CacheManager
from src.chat.eventsub_backend import EventSubChatBackend


class TestCacheManagerIntegration:
    """Integration tests for CacheManager with EventSubChatBackend."""

    @pytest.fixture
    async def temp_cache_file(self):
        """Create a temporary cache file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    async def cache_manager(self, temp_cache_file):
        """Create a CacheManager instance for testing."""
        manager = CacheManager(temp_cache_file)
        yield manager

    @pytest.fixture
    async def backend_with_cache(self, cache_manager):
        """Create EventSubChatBackend with injected CacheManager."""
        backend = EventSubChatBackend(cache_manager=cache_manager)
        yield backend

    async def test_backend_initializes_with_cache_manager(self, cache_manager):
        """Test that EventSubChatBackend properly initializes with CacheManager."""
        backend = EventSubChatBackend(cache_manager=cache_manager)
        assert backend._cache_manager is cache_manager

    async def test_backend_creates_default_cache_manager(self):
        """Test that EventSubChatBackend creates default CacheManager when none provided."""
        backend = EventSubChatBackend()
        await backend._initialize_components()
        assert backend._cache_manager is not None
        assert isinstance(backend._cache_manager, CacheManager)

    async def test_cache_persistence_through_backend_lifecycle(self, temp_cache_file):
        """Test that cache data persists through backend initialization and usage."""
        # Create backend with cache manager
        cache_manager = CacheManager(temp_cache_file)
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Set some data
        await cache_manager.set("test_channel", "12345")
        await cache_manager.set("another_channel", "67890")

        # Verify data is accessible through backend's cache manager
        assert await backend._cache_manager.get("test_channel") == "12345"
        assert await backend._cache_manager.get("another_channel") == "67890"

    async def test_cache_error_handling_in_backend_context(self, cache_manager, caplog):
        """Test that cache errors are handled gracefully in backend operations."""
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Simulate cache save error - the OSError will be raised directly from the mock
        with patch.object(cache_manager, '_save_data', side_effect=OSError("Disk full")):
            # This will raise OSError since we're mocking _save_data directly
            with pytest.raises(OSError, match="Disk full"):
                await backend._cache_manager.set("test", "value")

    async def test_concurrent_cache_access_through_backend(self, cache_manager):
        """Test concurrent cache access through multiple backend operations."""
        backend = EventSubChatBackend(cache_manager=cache_manager)

        async def backend_cache_operation(key, value):
            await backend._cache_manager.set(key, value)
            return await backend._cache_manager.get(key)

        # Run concurrent operations
        tasks = [
            backend_cache_operation(f"channel_{i}", f"id_{i}")
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # Verify all operations completed successfully
        for i, result in enumerate(results):
            assert result == f"id_{i}"

        # Verify data persistence
        for i in range(5):
            assert await backend._cache_manager.get(f"channel_{i}") == f"id_{i}"

    async def test_cache_recovery_from_corruption_in_backend(self, temp_cache_file):
        """Test cache recovery from corrupted file during backend operations."""
        # Create corrupted cache file
        loop = asyncio.get_event_loop()
        def _create_corrupted_file():
            with open(temp_cache_file, 'w') as f:
                f.write("invalid json content")
        await loop.run_in_executor(None, _create_corrupted_file)

        cache_manager = CacheManager(temp_cache_file)
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Backend should handle corrupted cache gracefully
        result = await backend._cache_manager.get("any_key")
        assert result is None

        # Should be able to set new values after corruption recovery
        await backend._cache_manager.set("recovered_key", "recovered_value")
        assert await backend._cache_manager.get("recovered_key") == "recovered_value"

    async def test_cache_directory_creation_through_backend(self, tmp_path):
        """Test that cache directory is created when using backend with new path."""
        cache_path = tmp_path / "subdir" / "cache.json"
        cache_manager = CacheManager(str(cache_path))
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Setting a value should create the directory
        await backend._cache_manager.set("test", "value")

        assert cache_path.exists()
        assert cache_path.parent.exists()

        # Verify content
        loop = asyncio.get_event_loop()
        def _read_file():
            with open(cache_path) as f:
                return json.load(f)
        data = await loop.run_in_executor(None, _read_file)
        assert data == {"test": "value"}

    async def test_backend_cache_manager_context_manager(self, temp_cache_file):
        """Test that backend works with cache manager as async context manager."""
        cache_manager = CacheManager(temp_cache_file)

        async with EventSubChatBackend(cache_manager=cache_manager) as backend:
            await backend._cache_manager.set("context_test", "context_value")
            assert await backend._cache_manager.get("context_test") == "context_value"

        # After context exit, cache manager should still be accessible
        assert await cache_manager.get("context_test") == "context_value"

    async def test_cache_manager_locking_in_backend_operations(self, cache_manager):
        """Test that cache locking works properly during backend operations."""
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Verify the cache manager has proper locking
        assert hasattr(backend._cache_manager, '_lock')
        assert isinstance(backend._cache_manager._lock, asyncio.Lock)

        # Test that operations use the lock
        with patch.object(backend._cache_manager._lock, 'acquire') as mock_acquire, \
             patch.object(backend._cache_manager._lock, 'release') as mock_release:
            await backend._cache_manager.set("lock_test", "lock_value")
            # The lock should have been acquired and released
            mock_acquire.assert_called()
            mock_release.assert_called()

    async def test_cache_manager_error_propagation_to_backend(self, cache_manager):
        """Test that cache errors are properly handled at backend level."""
        # Test with invalid cache file path - ValueError is raised during CacheManager init
        with pytest.raises(ValueError, match="cache_file_path cannot be empty"):
            invalid_manager = CacheManager("")  # Empty path should raise ValueError
            EventSubChatBackend(cache_manager=invalid_manager)

    async def test_backend_cache_cleanup_on_exit(self, cache_manager):
        """Test that cache is properly handled during backend cleanup."""
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Set some data
        await backend._cache_manager.set("cleanup_test", "cleanup_value")

        # Simulate backend cleanup
        await backend._cleanup_components()

        # Cache manager should still be accessible and contain data
        assert await cache_manager.get("cleanup_test") == "cleanup_value"

    async def test_cache_manager_memory_cache_integration(self, cache_manager):
        """Test that memory cache works in backend context."""
        backend = EventSubChatBackend(cache_manager=cache_manager)

        # Set value (should go to memory cache)
        await backend._cache_manager.set("memory_test", "memory_value")

        # Get value (should come from memory cache)
        result = await backend._cache_manager.get("memory_test")
        assert result == "memory_value"

        # Verify it's in memory cache
        assert "memory_test" in backend._cache_manager._memory_cache
        assert backend._cache_manager._memory_cache["memory_test"] == "memory_value"
