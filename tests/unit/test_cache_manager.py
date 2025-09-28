"""
Unit tests for CacheManager.

Tests the asynchronous file-based cache manager with concurrency control.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import patch

from src.chat.cache_manager import CacheManager


class TestCacheManager:
    """Test class for CacheManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_file = os.path.join(self.temp_dir, "test_cache.json")

    def teardown_method(self):
        """Teardown method called after each test."""
        # Clean up all files in temp directory
        for filename in os.listdir(self.temp_dir):
            file_path = os.path.join(self.temp_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except OSError:
                pass
        os.rmdir(self.temp_dir)

    @pytest.mark.asyncio
    async def test_set_and_get_basic(self):
        """Test basic set and get operations."""
        async with CacheManager(self.cache_file) as cache:
            # Set a value
            await cache.set("key1", "value1")

            # Get the value
            result = await cache.get("key1")
            assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        async with CacheManager(self.cache_file) as cache:
            result = await cache.get("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_contains_key(self):
        """Test contains method."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")

            assert await cache.contains("key1") is True
            assert await cache.contains("key2") is False

    @pytest.mark.asyncio
    async def test_delete_key(self):
        """Test delete operation."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")
            assert await cache.contains("key1") is True

            await cache.delete("key1")
            assert await cache.contains("key1") is False

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """Test clear operation."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")
            await cache.set("key2", "value2")

            assert await cache.contains("key1") is True
            assert await cache.contains("key2") is True

            await cache.clear()

            assert await cache.contains("key1") is False
            assert await cache.contains("key2") is False

    @pytest.mark.asyncio
    async def test_keys_method(self):
        """Test keys method."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")
            await cache.set("key2", "value2")

            keys = await cache.keys()
            assert set(keys) == {"key1", "key2"}

    @pytest.mark.asyncio
    async def test_memory_cache_eviction(self):
        """Test memory cache LRU eviction."""
        # Create cache with small memory size
        async with CacheManager(self.cache_file, max_cache_size=2) as cache:
            await cache.set("key1", "value1")
            await cache.set("key2", "value2")
            await cache.set("key3", "value3")  # This should evict key1

            # key1 should not be in memory anymore
            # But since we load from file, it should still be accessible
            result = await cache.get("key1")
            assert result == "value1"

    @pytest.mark.asyncio
    async def test_external_file_modification_invalidation(self):
        """Test that cache invalidates when file is modified externally."""
        async with CacheManager(self.cache_file) as cache:
            # Set initial value
            await cache.set("key1", "value1")

            # Verify it's cached
            result = await cache.get("key1")
            assert result == "value1"

            # Modify file externally (simulate external edit)
            external_data = {"key1": "modified_value", "key2": "new_value"}
            with open(self.cache_file, 'w') as f:
                json.dump(external_data, f, indent=2)

            # Get should return the modified value, not the cached one
            result = await cache.get("key1")
            assert result == "modified_value"

            # New key should also be accessible
            result2 = await cache.get("key2")
            assert result2 == "new_value"

    @pytest.mark.asyncio
    async def test_external_file_modification_contains(self):
        """Test contains method detects external modifications."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")
            assert await cache.contains("key1") is True

            # Modify file externally to remove the key
            external_data = {"key2": "value2"}
            with open(self.cache_file, 'w') as f:
                json.dump(external_data, f, indent=2)

            # contains should reflect the external change
            assert await cache.contains("key1") is False
            assert await cache.contains("key2") is True

    @pytest.mark.asyncio
    async def test_external_file_modification_keys(self):
        """Test keys method detects external modifications."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")
            keys = await cache.keys()
            assert keys == ["key1"]

            # Modify file externally
            external_data = {"key2": "value2", "key3": "value3"}
            with open(self.cache_file, 'w') as f:
                json.dump(external_data, f, indent=2)

            # keys should reflect the external change
            keys = await cache.keys()
            assert set(keys) == {"key2", "key3"}

    @pytest.mark.asyncio
    async def test_corrupted_json_recovery(self):
        """Test recovery from corrupted JSON file."""
        async with CacheManager(self.cache_file) as cache:
            await cache.set("key1", "value1")

            # Corrupt the file
            with open(self.cache_file, 'w') as f:
                f.write("invalid json")

            # Next operation should recover with empty cache
            result = await cache.get("key1")
            assert result is None

    @pytest.mark.asyncio
    async def test_empty_file_handling(self):
        """Test handling of empty cache file."""
        # Create empty file
        with open(self.cache_file, 'w') as f:
            pass

        async with CacheManager(self.cache_file) as cache:
            result = await cache.get("any_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        """Test behavior with nonexistent cache file."""
        nonexistent_file = os.path.join(self.temp_dir, "nonexistent.json")

        async with CacheManager(nonexistent_file) as cache:
            result = await cache.get("any_key")
            assert result is None

            # Setting should create the file
            await cache.set("key1", "value1")
            result = await cache.get("key1")
            assert result == "value1"