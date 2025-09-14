from __future__ import annotations

import json
import os
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
