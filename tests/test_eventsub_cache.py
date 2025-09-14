import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.chat.eventsub_backend import EventSubChatBackend


class TestEventSubCache:
    """Test cache saving functionality in EventSubChatBackend."""

    @patch("aiohttp.ClientSession")
    def test_save_id_cache_creates_directory_and_saves_file(self, mock_session):
        """Test that _save_id_cache creates parent directory and saves cache file."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"testchannel": "12345"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "subdir" / "cache.json"
            backend._cache_path = cache_path

            backend._save_id_cache()

            # Check that directory was created
            assert cache_path.parent.exists()
            assert cache_path.exists()

            # Check content
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            assert data == {"testchannel": "12345"}

    @patch("aiohttp.ClientSession")
    def test_save_id_cache_handles_permission_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for PermissionError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "readonly" / "cache.json"
            cache_path.parent.mkdir(parents=True)
            # Make parent directory read-only (simulate permission issue)
            cache_path.parent.chmod(0o444)

            backend._cache_path = cache_path

            backend._save_id_cache()

            # Check that error was logged
            assert any("Permission denied" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    def test_save_id_cache_handles_os_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for OSError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with patch("pathlib.Path.mkdir", side_effect=OSError("Disk full")):
            backend._cache_path = Path("/fake/path/cache.json")

            backend._save_id_cache()

            # Check that error was logged
            assert any("OS error" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    def test_save_id_cache_handles_file_not_found_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for FileNotFoundError."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.open", side_effect=FileNotFoundError("No such file")):
            backend._cache_path = Path("/fake/cache.json")

            backend._save_id_cache()

            # Check that error was logged
            assert any("File not found" in record.message for record in caplog.records)

    @patch("aiohttp.ClientSession")
    def test_save_id_cache_handles_unexpected_error(self, mock_session, caplog):
        """Test that _save_id_cache logs detailed error for unexpected exceptions."""
        backend = EventSubChatBackend()
        backend._channel_ids = {"test": "123"}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            backend._cache_path = cache_path

            with patch("json.dump", side_effect=ValueError("Invalid JSON")):
                backend._save_id_cache()

                # Check that error was logged
                assert any("Unexpected error" in record.message for record in caplog.records)
