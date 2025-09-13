import json
from pathlib import Path

import pytest

from src.config.async_persistence import (
    async_update_user_in_config,
    flush_pending_updates,
    queue_user_update,
)


@pytest.mark.asyncio
async def test_queue_vs_direct_last_wins(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "users_concurrency.json"
    # Start with base user via direct write
    base = {"username": "zoe", "channels": ["zoe"], "access_token": "a" * 25}
    await async_update_user_in_config(base, str(cfg))

    # Rapid queued updates modifying channels and a direct write interleaving
    await queue_user_update({"username": "zoe", "channels": ["zoe", "x"], "access_token": "a" * 25}, str(cfg))
    await queue_user_update({"username": "zoe", "channels": ["zoe", "x", "y"], "access_token": "a" * 25}, str(cfg))
    # Direct write should be serialized with per-user lock (channels -> only zoe + y + z)
    await async_update_user_in_config({"username": "zoe", "channels": ["zoe", "z"], "access_token": "a" * 25}, str(cfg))
    # Another queued update (should overwrite prior queued state before flush)
    await queue_user_update({"username": "zoe", "channels": ["zoe", "final"], "access_token": "a" * 25}, str(cfg))

    # Force flush queued updates
    await flush_pending_updates(str(cfg))

    data = json.loads(cfg.read_text())
    users = data["users"] if isinstance(data, dict) and "users" in data else data
    # Expect last queued update to dominate (final) combined with direct last value before flush overwritten by queued.
    zoe_entry = next(u for u in users if u.get("username") == "zoe")
    assert set(zoe_entry["channels"]) == {"#zoe", "#final"}
