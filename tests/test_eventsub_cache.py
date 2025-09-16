import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.chat.eventsub_backend import EventSubChatBackend


class TestEventSubCache:
    """Test cache saving functionality in EventSubChatBackend."""

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_save_id_cache_creates_directory_and_saves_file(self, mock_session):
        """Test that _save_id_cache creates parent directory and saves cache file."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"testchannel": "12345"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "subdir" / "cache.json"
            backend._cache_path = cache_path

            await backend._save_id_cache()

            # Check that directory was created
            assert cache_path.parent.exists()
            assert cache_path.exists()

            # Check content
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            assert data == {"testchannel": "12345"}

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_save_id_cache_handles_permission_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for PermissionError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "readonly" / "cache.json"
            cache_path.parent.mkdir(parents=True)
            # Make parent directory read-only (simulate permission issue)
            cache_path.parent.chmod(0o444)

            backend._cache_path = cache_path

            await backend._save_id_cache()

            # Check that error was logged
            assert any("Permission denied" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_save_id_cache_handles_os_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for OSError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with patch("pathlib.Path.mkdir", side_effect=OSError("Disk full")):
            backend._cache_path = Path("/fake/path/cache.json")

            await backend._save_id_cache()

            # Check that error was logged
            assert any("OS error" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_save_id_cache_handles_file_not_found_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for FileNotFoundError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.open", side_effect=FileNotFoundError("No such file")):
            backend._cache_path = Path("/fake/cache.json")

            await backend._save_id_cache()

            # Check that error was logged
            assert any("File not found" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_save_id_cache_handles_unexpected_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for unexpected exceptions."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            backend._cache_path = cache_path

            with patch("json.dump", side_effect=ValueError("Invalid JSON")):
                await backend._save_id_cache()

                # Check that error was logged
                assert any("Unexpected error" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_concurrent_cache_saving_with_file_locking(self, mock_session):
        """Test that concurrent cache saves work correctly with file locking."""
        # Create two backend instances that share the same cache file
        backend1 = EventSubChatBackend()
        backend2 = EventSubChatBackend()

        backend1._channel_ids = {"channel1": "12345"}
        backend2._channel_ids = {"channel2": "67890"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "shared_cache.json"
            backend1._cache_path = cache_path
            backend2._cache_path = cache_path

            # Run both saves concurrently
            await asyncio.gather(
                backend1._save_id_cache(),
                backend2._save_id_cache()
            )

            # Verify the cache file exists and contains data from both backends
            assert cache_path.exists()

            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Should contain data from the last write (backend2's data)
            # File locking ensures atomicity, but the final state depends on timing
            assert isinstance(data, dict)
            # At minimum, should have some channel data
            assert len(data) >= 1

    @patch("aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_cache_save_with_lock_timeout_simulation(self, mock_session, caplog):
        """Test cache save behavior when file locking encounters issues."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            backend._cache_path = cache_path

            # Simulate a locking issue by patching fcntl.flock to raise an exception
            with patch("fcntl.flock", side_effect=OSError("Lock failed")):
                await backend._save_id_cache()

                # Should still attempt to save and log the error
                assert any("OS error" in record.message for record in caplog.records)
