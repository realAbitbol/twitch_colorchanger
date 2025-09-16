"""Unit tests for CacheManager."""

import asyncio
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from src.chat.cache_manager import CacheManager
from src.errors.eventsub import CacheError


class TestCacheManager:
    """Test suite for CacheManager."""

    @pytest.fixture
    async def cache_manager(self):
        """Create a temporary CacheManager for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        manager = CacheManager(temp_path)

        yield manager

        # Cleanup
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    @pytest.fixture
    async def populated_cache(self):
        """Create a CacheManager with some initial data."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key1": "value1", "key2": 42}, f)
            temp_path = f.name

        manager = CacheManager(temp_path)

        yield manager

        try:
            os.unlink(temp_path)
        except OSError:
            pass

    async def test_init_valid_path(self):
        """Test initialization with valid path."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)
            assert manager._cache_file_path == temp_path
            assert isinstance(manager._lock, asyncio.Lock)
        finally:
            os.unlink(temp_path)

    async def test_init_empty_path_raises(self):
        """Test initialization with empty path raises ValueError."""
        with pytest.raises(ValueError, match="cache_file_path cannot be empty"):
            CacheManager("")

    async def test_get_nonexistent_key(self, cache_manager):
        """Test getting a key that doesn't exist."""
        result = await cache_manager.get("nonexistent")
        assert result is None

    async def test_set_and_get(self, cache_manager):
        """Test setting and getting a value."""
        await cache_manager.set("test_key", "test_value")
        result = await cache_manager.get("test_key")
        assert result == "test_value"

    async def test_set_multiple_values(self, cache_manager):
        """Test setting multiple values."""
        await cache_manager.set("key1", "value1")
        await cache_manager.set("key2", 42)
        await cache_manager.set("key3", {"nested": "dict"})

        assert await cache_manager.get("key1") == "value1"
        assert await cache_manager.get("key2") == 42
        assert await cache_manager.get("key3") == {"nested": "dict"}

    async def test_delete_key(self, cache_manager):
        """Test deleting a key."""
        await cache_manager.set("test_key", "test_value")
        assert await cache_manager.get("test_key") == "test_value"

        await cache_manager.delete("test_key")
        assert await cache_manager.get("test_key") is None

    async def test_delete_nonexistent_key(self, cache_manager):
        """Test deleting a key that doesn't exist."""
        # Should not raise an error
        await cache_manager.delete("nonexistent")
        assert await cache_manager.get("nonexistent") is None

    async def test_clear_cache(self, cache_manager):
        """Test clearing the entire cache."""
        await cache_manager.set("key1", "value1")
        await cache_manager.set("key2", "value2")

        assert await cache_manager.get("key1") == "value1"
        assert await cache_manager.get("key2") == "value2"

        await cache_manager.clear()

        assert await cache_manager.get("key1") is None
        assert await cache_manager.get("key2") is None

    async def test_contains_key(self, cache_manager):
        """Test checking if a key exists."""
        await cache_manager.set("existing_key", "value")
        assert await cache_manager.contains("existing_key") is True
        assert await cache_manager.contains("nonexistent") is False

    async def test_keys_empty_cache(self, cache_manager):
        """Test getting keys from empty cache."""
        keys = await cache_manager.keys()
        assert keys == []

    async def test_keys_populated_cache(self, cache_manager):
        """Test getting keys from populated cache."""
        await cache_manager.set("key1", "value1")
        await cache_manager.set("key2", "value2")

        keys = await cache_manager.keys()
        assert set(keys) == {"key1", "key2"}

    async def test_load_existing_file(self, populated_cache):
        """Test loading data from existing file."""
        assert await populated_cache.get("key1") == "value1"
        assert await populated_cache.get("key2") == 42

    async def test_save_creates_directory(self):
        """Test that save creates necessary directories."""
        temp_dir = tempfile.mkdtemp()
        cache_path = os.path.join(temp_dir, "subdir", "cache.json")

        try:
            manager = CacheManager(cache_path)
            await manager.set("test", "value")

            assert os.path.exists(cache_path)
            loop = asyncio.get_event_loop()
            def _read_file():
                with open(cache_path) as f:
                    return json.load(f)
            data = await loop.run_in_executor(None, _read_file)
            assert data == {"test": "value"}
        finally:
            # Cleanup
            import shutil
            shutil.rmtree(temp_dir)

    async def test_invalid_json_file_recovers_gracefully(self):
        """Test that invalid JSON in file recovers gracefully with empty cache."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)
            # Should recover gracefully and return None for any key
            result = await manager.get("any_key")
            assert result is None
        finally:
            # File might have been renamed during recovery
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            # Also try to clean up backup file
            try:
                os.unlink(f"{temp_path}.corrupted")
            except OSError:
                pass

    async def test_file_permission_error_raises_cache_error(self):
        """Test that file permission errors raise CacheError."""
        # Create a directory and make it read-only
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "cache.json")

        try:
            # Create initial file asynchronously
            loop = asyncio.get_event_loop()
            def _create_file():
                with open(temp_path, 'w') as f:
                    json.dump({"test": "data"}, f)
            await loop.run_in_executor(None, _create_file)

            # Make directory read-only (prevent temp file creation)
            os.chmod(temp_dir, 0o444)

            manager = CacheManager(temp_path)
            # Try to save (should fail due to directory permissions)
            with pytest.raises(CacheError) as exc_info:
                await manager.set("new_key", "value")
            assert "Failed to save cache" in str(exc_info.value)
            assert exc_info.value.operation_type == "save_cache"
        finally:
            os.chmod(temp_dir, 0o755)  # noqa: S103 # Restore permissions for cleanup
            import shutil
            shutil.rmtree(temp_dir)

    async def test_concurrent_access(self):
        """Test concurrent access to cache."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            async def set_value(key, value):
                await manager.set(key, value)

            # Run multiple concurrent operations
            tasks = [
                set_value(f"key{i}", f"value{i}")
                for i in range(5)
            ]
            await asyncio.gather(*tasks)

            # Verify all values were set
            for i in range(5):
                assert await manager.get(f"key{i}") == f"value{i}"
        finally:
            os.unlink(temp_path)

    async def test_async_context_manager(self):
        """Test async context manager functionality."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            async with CacheManager(temp_path) as manager:
                await manager.set("test", "value")
                assert await manager.get("test") == "value"

            # After context exit, manager should still work
            assert await manager.get("test") == "value"
        finally:
            os.unlink(temp_path)

    async def test_save_handles_os_error(self, caplog):
        """Test that save handles OSError during file operations."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            # Patch os.makedirs to raise OSError
            with patch("os.makedirs", side_effect=OSError("Disk full")):
                with pytest.raises(CacheError) as exc_info:
                    await manager.set("test", "value")
                assert "Failed to save cache" in str(exc_info.value)
                assert exc_info.value.operation_type == "save_cache"
        finally:
            os.unlink(temp_path)

    async def test_save_handles_file_not_found_error(self, caplog):
        """Test that save handles FileNotFoundError during file operations."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            with patch("tempfile.mkstemp", side_effect=FileNotFoundError("No such file")), \
                 patch("pathlib.Path.open", side_effect=FileNotFoundError("No such file")):
                with pytest.raises(CacheError) as exc_info:
                    await manager.set("test", "value")
                assert "Failed to save cache" in str(exc_info.value)
                assert exc_info.value.operation_type == "save_cache"
        finally:
            os.unlink(temp_path)

    async def test_save_handles_unexpected_error(self, caplog):
        """Test that save handles unexpected exceptions during file operations."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            with patch("json.dump", side_effect=ValueError("Invalid JSON")):
                # The CacheManager only catches OSError, not ValueError
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await manager.set("test", "value")
        finally:
            os.unlink(temp_path)

    async def test_concurrent_saving_with_locking(self):
        """Test concurrent cache operations with proper locking."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            async def concurrent_set(key, value):
                await manager.set(key, value)

            # Run multiple concurrent operations
            tasks = [
                concurrent_set(f"key{i}", f"value{i}")
                for i in range(10)
            ]
            await asyncio.gather(*tasks)

            # Verify all values were set correctly
            for i in range(10):
                assert await manager.get(f"key{i}") == f"value{i}"
        finally:
            os.unlink(temp_path)

    async def test_save_with_lock_timeout_simulation(self, caplog):
        """Test save behavior when file locking encounters issues."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = CacheManager(temp_path)

            # Simulate a locking issue by making the save operation fail
            async def failing_save():
                with patch("json.dump", side_effect=OSError("Lock failed")):
                    try:
                        await manager.set("test", "value")
                    except CacheError:
                        pass  # Expected

            await failing_save()

            # Verify the cache file wasn't corrupted
            # Should still be able to read existing data or handle gracefully
            result = await manager.get("test")
            assert result is None  # Since save failed
        finally:
            os.unlink(temp_path)
