from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.config.async_persistence import (
    flush_pending_updates,
    queue_user_update,
)


def _read_config(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "users" in raw and isinstance(raw["users"], list):
        return [u for u in raw["users"] if isinstance(u, dict)]
    if isinstance(raw, list):
        return [u for u in raw if isinstance(u, dict)]
    if isinstance(raw, dict) and "username" in raw:
        return [raw]
    return []


@pytest.mark.asyncio
async def test_queue_and_flush_coalesces(tmp_path: Path) -> None:
    cfg = tmp_path / "users.json"
    # Queue multiple rapid updates for same user (should merge last fields)
    await queue_user_update({"username": "Alice", "access_token": "one"}, str(cfg))
    await queue_user_update({"username": "Alice", "refresh_token": "two"}, str(cfg))
    await queue_user_update({"username": "Alice", "channels": ["#x", "X"]}, str(cfg))
    # Force flush
    await flush_pending_updates(str(cfg))
    data = _read_config(cfg)
    if len(data) != 1:
        raise AssertionError(f"Expected single user record, got {data}")
    rec = data[0]
    if rec.get("access_token") != "one":
        raise AssertionError("First field should persist (merged)")
    if rec.get("refresh_token") != "two":
        raise AssertionError("Merged refresh token missing")
    if sorted(rec.get("channels", [])) != ["x"]:
        raise AssertionError(f"Channels not normalized or deduped: {rec.get('channels')}")


@pytest.mark.asyncio
async def test_debounce_batching_groups_multiple_users(tmp_path: Path) -> None:
    cfg = tmp_path / "users2.json"
    # Schedule updates and let debounce elapse
    await queue_user_update({"username": "Bob", "enabled": True}, str(cfg))
    await queue_user_update({"username": "Carol", "enabled": False}, str(cfg))
    # Sleep past debounce window to allow automatic flush (plus small buffer)
    await asyncio.sleep(0.35)
    data = _read_config(cfg)
    usernames = {u.get("username") for u in data}
    if usernames != {"Bob", "Carol"}:
        raise AssertionError(f"Expected Bob & Carol in file, got {usernames}")


@pytest.mark.asyncio
async def test_concurrent_queue_safe(tmp_path: Path) -> None:
    cfg = tmp_path / "users3.json"
    # Launch multiple queue operations concurrently for same user
    # Rapid successive updates adjusting channels list; last write's channels should
    # normalize to unique lowercase entries (UserConfig normalization logic).
    await asyncio.gather(
        *[
            queue_user_update(
                {"username": "Eve", "channels": ["#A", f"#chan{i}", "chan{i}"]},
                str(cfg),
            )
            for i in range(5)
        ]
    )
    await flush_pending_updates(str(cfg))
    data = _read_config(cfg)
    if len(data) != 1:
        raise AssertionError("Expected single merged record for Eve")
    final_record = data[0]
    chs = final_record.get("channels", [])
    # Expect normalization removed duplicates and lowercased names, includes 'a' and last chan
    if not chs:
        raise AssertionError("Channels list empty after merges")
    if any(c != c.lower() for c in chs):
        raise AssertionError(f"Channels not lowercased: {chs}")
    if len(chs) != len(set(chs)):
        raise AssertionError(f"Channels not deduplicated: {chs}")
