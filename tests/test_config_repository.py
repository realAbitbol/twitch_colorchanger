from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.repository import ConfigRepository


@pytest.mark.asyncio
async def test_repository_skip_checksum(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "alpha", "channels": ["a"], "enabled": True}]
    wrote_first = repo.save_users(users)
    assert wrote_first is True
    mtime_first = cfg.stat().st_mtime
    # Second save identical should skip
    wrote_second = repo.save_users(users)
    assert wrote_second is False
    assert cfg.stat().st_mtime == mtime_first


@pytest.mark.asyncio
async def test_repository_backup_rotation(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    # Perform multiple distinct writes to trigger backups; older than 3 should be pruned
    for i in range(5):
        users = [{"username": f"user{i}", "channels": [f"c{i}"], "enabled": True}]
        repo.save_users(users)
    backups = sorted(tmp_path.glob("users.conf.bak.*"))
    assert len(backups) <= 3, f"Expected at most 3 backups, found {len(backups)}"
    # Ensure latest file contains last user
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["users"][0]["username"] == "user4"


# Tests for load_raw: cache/JSON parse/validation/file errors (6 tests)

def test_load_raw_cache_hit(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": [{"username": "test"}]}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users1 = repo.load_raw()
    assert users1 == [{"username": "test"}]
    # Modify file but mock os.stat to return same mtime and size (simulate cache hit)
    cfg.write_text('{"users": [{"username": "changed"}]}', encoding="utf-8")
    from unittest.mock import MagicMock
    mock_stat = MagicMock()
    mock_stat.st_mtime = repo._file_mtime
    mock_stat.st_size = repo._file_size
    with patch('src.config.repository.os.stat', return_value=mock_stat):
        users2 = repo.load_raw()
        assert users2 == [{"username": "test"}]  # Should return cached


def test_load_raw_json_parse_error(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": invalid}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == []


def test_load_raw_validation_not_list(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": "not_a_list"}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == []


def test_load_raw_file_not_found(tmp_path: Path):
    cfg = tmp_path / "nonexistent.conf"
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == []


def test_load_raw_os_error(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": []}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    with patch('os.stat', side_effect=OSError):
        users = repo.load_raw()
        assert users == []


def test_load_raw_valid_users_key(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": [{"username": "valid"}]}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == [{"username": "valid"}]


# Tests for save_users: checksum/atomic write/backup (6 tests)

def test_save_users_checksum_skip(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "test"}]
    assert repo.save_users(users) is True
    assert repo.save_users(users) is False  # Skip due to checksum


def test_save_users_atomic_write_success(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "atomic"}]
    assert repo.save_users(users) is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == {"users": users}


def test_save_users_backup_creation(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": [{"username": "old"}]}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users = [{"username": "new"}]
    repo.save_users(users)
    backups = list(tmp_path.glob("users.conf.bak.*"))
    assert len(backups) == 1


def test_save_users_directory_creation(tmp_path: Path):
    subdir = tmp_path / "subdir"
    cfg = subdir / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "dir"}]
    repo.save_users(users)
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == {"users": users}


def test_save_users_atomic_write_permission_error(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "perm"}]
    with patch('tempfile.NamedTemporaryFile', side_effect=PermissionError), pytest.raises(PermissionError):
        repo.save_users(users)


def test_save_users_lock_handling(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    users = [{"username": "lock"}]
    # Mock flock to raise error, save should fail
    with patch('fcntl.flock', side_effect=OSError), pytest.raises(OSError):
        repo.save_users(users)


# Tests for verify_readback (3 tests)

def test_verify_readback_success(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"users": [{"username": "verify"}]}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    # Should not raise
    repo.verify_readback()


def test_verify_readback_file_error(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    repo = ConfigRepository(str(cfg))
    # File doesn't exist, should handle gracefully
    repo.verify_readback()


def test_verify_readback_invalid_json(tmp_path: Path):
    cfg = tmp_path / "users.conf"
    cfg.write_text('invalid json', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    # Should handle error gracefully
    repo.verify_readback()

def test_config_repository_init_invalid_path():
    """Test ConfigRepository initialization with invalid file paths."""
    with pytest.raises(TypeError):
        ConfigRepository(None)
    with pytest.raises(TypeError):
        ConfigRepository(123)


def test_load_file_not_found(tmp_path: Path):
    """Test load method when configuration file is not found."""
    cfg = tmp_path / "nonexistent.conf"
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == []


def test_save_permission_denied(tmp_path: Path):
    """Test save method with permission denied errors."""
    cfg = tmp_path / "readonly.conf"
    cfg.write_text('{"users": []}', encoding="utf-8")
    repo = ConfigRepository(str(cfg))
    users = [{"username": "test"}]
    with patch('tempfile.NamedTemporaryFile', side_effect=PermissionError), pytest.raises((OSError, PermissionError)):
        repo.save_users(users)


def test_update_invalid_data(tmp_path: Path):
    """Test update method with invalid data types or values."""
    cfg = tmp_path / "invalid.conf"
    repo = ConfigRepository(str(cfg))
    # Invalid data: not list
    with pytest.raises((TypeError, AttributeError)):
        repo.save_users("invalid")


def test_delete_non_existent_key(tmp_path: Path):
    """Test delete method with non-existent configuration keys."""
    cfg = tmp_path / "users.conf"
    cfg.write_text('{"other": []}', encoding="utf-8")  # missing users key
    repo = ConfigRepository(str(cfg))
    users = repo.load_raw()
    assert users == []  # treats as non-existent key


def test_race_condition_fix_chmod_timing_security(tmp_path: Path):
    """Test that chmod timing fix prevents race condition in file permissions.

    Security verification test to ensure the final config file always has
    secure 0o600 permissions even under concurrent access scenarios.
    """
    cfg = tmp_path / "race_test.conf"
    repo = ConfigRepository(str(cfg))

    # Test 1: Basic race condition simulation
    users = [{"username": "race_test", "channels": ["test"], "enabled": True}]

    # Save the configuration
    result = repo.save_users(users)
    assert result is True

    # Verify the file exists and has correct permissions
    assert cfg.exists()
    file_mode = cfg.stat().st_mode
    file_permissions = stat.filemode(file_mode)

    # The file should have secure 0o600 permissions (owner read/write only)
    assert oct(file_mode & 0o777) == oct(0o600), f"Expected 0o600 permissions, got {oct(file_mode & 0o777)} ({file_permissions})"


def test_concurrent_file_access_race_condition_prevention(tmp_path: Path):
    """Test race condition prevention with concurrent file access simulation.

    Simulates multiple threads trying to write to the same config file
    simultaneously to verify the chmod timing fix ensures secure permissions.
    """
    cfg = tmp_path / "concurrent_test.conf"
    repo = ConfigRepository(str(cfg))

    results = []
    exceptions = []

    def save_config(user_id: int):
        """Simulate concurrent save operations."""
        try:
            users = [{"username": f"user{user_id}", "channels": [f"ch{user_id}"], "enabled": True}]
            result = repo.save_users(users)
            results.append((user_id, result))

            # Verify file permissions after each save
            if cfg.exists():
                file_mode = cfg.stat().st_mode
                permissions = oct(file_mode & 0o777)
                if permissions != oct(0o600):
                    exceptions.append(f"User {user_id}: Expected 0o600, got {permissions}")

        except Exception as e:
            exceptions.append(f"User {user_id}: {str(e)}")

    # Create multiple threads to simulate concurrent access
    threads = []
    num_threads = 5

    for i in range(num_threads):
        thread = threading.Thread(target=save_config, args=(i,))
        threads.append(thread)

    # Start all threads
    for thread in threads:
        thread.start()
        # Small delay to increase chance of race conditions
        time.sleep(0.01)

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Verify all operations completed
    assert len(results) == num_threads, f"Expected {num_threads} results, got {len(results)}"

    # Verify no permission exceptions occurred
    assert len(exceptions) == 0, f"Permission errors occurred: {exceptions}"

    # Final verification: file should exist and have secure permissions
    assert cfg.exists(), "Config file should exist after concurrent operations"

    final_mode = cfg.stat().st_mode
    final_permissions = oct(final_mode & 0o777)
    assert final_permissions == oct(0o600), f"Final permissions should be 0o600, got {final_permissions}"

    # Verify the final content is valid
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "users" in data
    assert len(data["users"]) == 1  # Last write should win
    assert data["users"][0]["username"].startswith("user")


def test_chmod_race_condition_with_permission_interference(tmp_path: Path):
    """Test chmod race condition fix with simulated permission interference.

    Simulates a scenario where external processes might interfere with
    file permissions during the atomic write operation.
    """
    cfg = tmp_path / "interference_test.conf"
    repo = ConfigRepository(str(cfg))

    # Track chmod calls to verify the fix
    chmod_calls = []

    original_chmod = os.chmod

    def mock_chmod(path, mode):
        """Mock chmod to track calls and simulate interference."""
        chmod_calls.append((str(path), oct(mode)))
        # Simulate race condition: on temp file chmod, change target file permissions
        if str(path).endswith('.tmp') and cfg.exists():
            try:
                # Simulate external process changing permissions during temp file chmod
                original_chmod(cfg, 0o644)  # Less secure permissions
            except (OSError, PermissionError):
                pass  # Ignore permission errors in simulation
        return original_chmod(path, mode)

    users = [{"username": "interference_test", "channels": ["test"], "enabled": True}]

    with patch('os.chmod', side_effect=mock_chmod):
        result = repo.save_users(users)
        assert result is True

    # Verify chmod was called for both temp file and final file
    assert len(chmod_calls) >= 2, f"Expected at least 2 chmod calls, got {len(chmod_calls)}"

    # Find the final file chmod call (should be 0o600)
    final_chmod = None
    for path, mode in chmod_calls:
        if path == str(cfg):
            final_chmod = (path, mode)
            break

    assert final_chmod is not None, "Final file chmod call not found"
    assert final_chmod[1] == oct(0o600), f"Final file should have 0o600 permissions, got {final_chmod[1]}"

    # Verify final file has correct permissions
    assert cfg.exists()
    final_mode = cfg.stat().st_mode
    final_permissions = oct(final_mode & 0o777)
    assert final_permissions == oct(0o600), f"Final file permissions should be 0o600, got {final_permissions}"


def test_secure_permissions_maintained_under_load(tmp_path: Path):
    """Test that secure permissions are maintained under high load.

    Simulates high-frequency save operations to ensure the race condition
    fix consistently maintains secure 0o600 permissions.
    """
    cfg = tmp_path / "load_test.conf"
    repo = ConfigRepository(str(cfg))

    # Perform many rapid saves
    for i in range(10):
        users = [{"username": f"load_user_{i}", "channels": [f"ch_{i}"], "enabled": True}]
        result = repo.save_users(users)
        assert result is True

        # After each save, verify permissions are still secure
        if cfg.exists():
            file_mode = cfg.stat().st_mode
            permissions = oct(file_mode & 0o777)
            assert permissions == oct(0o600), f"Permissions not secure after save {i}: {permissions}"

    # Final verification
    assert cfg.exists()
    final_mode = cfg.stat().st_mode
    final_permissions = oct(final_mode & 0o777)
    assert final_permissions == oct(0o600), f"Final permissions should be 0o600, got {final_permissions}"

    # Verify content is valid
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "users" in data
    assert len(data["users"]) == 1
    assert data["users"][0]["username"] == "load_user_9"  # Last write
