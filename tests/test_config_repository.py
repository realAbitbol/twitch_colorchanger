from __future__ import annotations

import json
from pathlib import Path

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
