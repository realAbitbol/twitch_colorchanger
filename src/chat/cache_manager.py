"""CacheManager for asynchronous file-based caching with concurrency control.

This module provides a CacheManager class that handles persistent storage of
key-value data using JSON serialization, with proper asynchronous file I/O
and locking mechanisms to ensure thread-safety in concurrent environments.
Includes in-memory LRU cache for performance and atomic file writes.
"""

import asyncio
import json
import logging
import os
import tempfile
from collections import OrderedDict
from typing import Any

from src.errors.eventsub import CacheError

from .protocols import CacheManagerProtocol

logger = logging.getLogger(__name__)


class CacheManager(CacheManagerProtocol):
    """Asynchronous file-based cache manager with concurrency control and LRU memory cache.

    This class provides a thread-safe interface for storing and retrieving
    key-value data from a JSON file, using asyncio.Lock for synchronization
    and proper error handling with custom EventSub exceptions.

    Features:
    - Persistent file-based storage with atomic writes
    - In-memory LRU cache for performance
    - Automatic recovery from corrupted JSON files
    - Thread-safe concurrent access

    The cache supports basic CRUD operations and is designed for use in
    asynchronous contexts, particularly for caching Twitch user IDs and
    other EventSub-related data.

    Attributes:
        _cache_file_path (str): Path to the JSON cache file.
        _lock (asyncio.Lock): Lock for synchronizing file operations.
        _memory_cache (OrderedDict): In-memory LRU cache.
        _max_cache_size (int): Maximum size of memory cache.

    Example:
        >>> async with CacheManager("cache.json") as cache:
        ...     await cache.set("user_id", "12345")
        ...     user_id = await cache.get("user_id")
        ...     print(user_id)  # Output: 12345
    """

    def __init__(self, cache_file_path: str, max_cache_size: int = 1000) -> None:
        """Initialize the CacheManager.

        Args:
            cache_file_path (str): Path to the JSON file used for caching.
                                    The directory will be created if it doesn't exist.
            max_cache_size (int): Maximum number of entries in memory cache.

        Raises:
            ValueError: If cache_file_path is empty or None.
        """
        if not cache_file_path:
            raise ValueError("cache_file_path cannot be empty")

        self._cache_file_path = cache_file_path
        self._lock = asyncio.Lock()
        self._memory_cache: OrderedDict[str, Any] = OrderedDict()
        self._max_cache_size = max_cache_size

    def _get_from_memory(self, key: str) -> Any:
        """Get value from memory cache, moving to end (most recent)."""
        if key in self._memory_cache:
            # Move to end (most recently used)
            self._memory_cache.move_to_end(key)
            return self._memory_cache[key]
        return None

    def _put_in_memory(self, key: str, value: Any) -> None:
        """Put value in memory cache with LRU eviction."""
        if key in self._memory_cache:
            # Update existing and move to end
            self._memory_cache.move_to_end(key)
        else:
            # Add new entry
            if len(self._memory_cache) >= self._max_cache_size:
                # Remove least recently used
                self._memory_cache.popitem(last=False)
        self._memory_cache[key] = value

    def _invalidate_memory(self, key: str) -> None:
        """Remove key from memory cache."""
        self._memory_cache.pop(key, None)

    def _clear_memory(self) -> None:
        """Clear all entries from memory cache."""
        self._memory_cache.clear()

    async def _load_data(self) -> dict[str, Any]:
        """Load cache data from file asynchronously with recovery.

        Returns:
            Dict[str, Any]: The loaded cache data, or empty dict if file doesn't exist or is corrupted.

        Raises:
            CacheError: If file cannot be read (non-corruption errors).
        """
        loop = asyncio.get_event_loop()
        try:
            if not os.path.exists(self._cache_file_path):
                return {}

            def _read_file():
                with open(self._cache_file_path) as f:
                    content = f.read()
                    if not content.strip():
                        return {}
                    return json.loads(content)

            data = await loop.run_in_executor(None, _read_file)
            return data
        except json.JSONDecodeError as e:
            # Recovery: log warning and return empty dict
            logger.warning(
                f"Corrupted JSON in cache file {self._cache_file_path}, recovering with empty cache: {e}"
            )
            # Try to backup corrupted file
            try:
                backup_path = f"{self._cache_file_path}.corrupted"
                os.rename(self._cache_file_path, backup_path)
                logger.info(f"Backed up corrupted cache to {backup_path}")
            except OSError:
                pass  # Ignore backup failure
            return {}
        except OSError as e:
            raise CacheError(
                f"Failed to load cache from {self._cache_file_path}: {e}",
                operation_type="load_cache",
            ) from e

    async def _save_data(self, data: dict[str, Any]) -> None:
        """Save cache data to file asynchronously with atomic writes.

        Args:
            data (Dict[str, Any]): The cache data to save.

        Raises:
            CacheError: If file cannot be written.
        """
        loop = asyncio.get_event_loop()
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._cache_file_path), exist_ok=True)

            def _write_atomic():
                # Write to temporary file first
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=os.path.dirname(self._cache_file_path),
                    prefix=os.path.basename(self._cache_file_path) + ".tmp",
                    suffix=".json",
                )
                try:
                    with os.fdopen(temp_fd, "w") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    # Atomic replace
                    os.replace(temp_path, self._cache_file_path)
                except Exception:
                    # Clean up temp file on error
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                    raise

            await loop.run_in_executor(None, _write_atomic)
        except OSError as e:
            raise CacheError(
                f"Failed to save cache to {self._cache_file_path}: {e}",
                operation_type="save_cache",
            ) from e

    async def get(self, key: str) -> Any:
        """Retrieve a value from the cache.

        Args:
            key (str): The key to retrieve.

        Returns:
            Any: The value associated with the key, or None if not found.
        """
        # Check memory cache first
        value = self._get_from_memory(key)
        if value is not None:
            return value

        # Load from file
        async with self._lock:
            data = await self._load_data()
            value = data.get(key)
            if value is not None:
                self._put_in_memory(key, value)
            return value

    async def set(self, key: str, value: Any) -> None:
        """Store a value in the cache.

        Args:
            key (str): The key to store.
            value (Any): The value to store.
        """
        async with self._lock:
            data = await self._load_data()
            data[key] = value
            await self._save_data(data)
            # Update memory cache
            self._put_in_memory(key, value)

    async def delete(self, key: str) -> None:
        """Remove a key from the cache.

        Args:
            key (str): The key to remove.
        """
        async with self._lock:
            data = await self._load_data()
            data.pop(key, None)
            await self._save_data(data)
            # Remove from memory cache
            self._invalidate_memory(key)

    async def clear(self) -> None:
        """Clear all data from the cache."""
        async with self._lock:
            await self._save_data({})
            # Clear memory cache
            self._clear_memory()

    async def contains(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key (str): The key to check.

        Returns:
            bool: True if the key exists, False otherwise.
        """
        # Check memory cache first
        if self._get_from_memory(key) is not None:
            return True

        # Check file
        async with self._lock:
            data = await self._load_data()
            exists = key in data
            if exists:
                self._put_in_memory(key, data[key])
            return exists

    async def keys(self) -> list[str]:
        """Get all keys in the cache.

        Returns:
            list[str]: List of all keys in the cache.
        """
        async with self._lock:
            data = await self._load_data()
            return list(data.keys())

    async def __aenter__(self):
        """Enter the async context manager.

        Returns:
            CacheManager: The cache manager instance.
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager.

        This method ensures proper cleanup of resources. Currently,
        no specific cleanup is needed as operations are atomic.
        """
        pass
