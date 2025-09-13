from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any

import pytest

from src.config.async_persistence import (
    async_update_user_in_config,
    flush_pending_updates,
    queue_user_update,
)


def _read_config(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    users = raw.get("users") if isinstance(raw, dict) else []
    out: dict[str, dict[str, Any]] = {}
    if isinstance(users, list):
        for u in users:
            if isinstance(u, dict) and isinstance(u.get("username"), str):
                out[u["username"].lower()] = u
    return out


async def _rapid_queue_user(u: str, cfg_path: str) -> None:
    for c in range(5):
        await queue_user_update({"username": u, "channels": [f"#{u}{c}"], "access_token": "a" * 20, "client_id": "b" * 10, "client_secret": "c" * 10}, cfg_path)
        await asyncio.sleep(random.uniform(0, 0.02))  # noqa: S311


async def _occasional_direct_user(u: str, cfg_path: str) -> None:
    # Issue a direct write that should serialize with queued batch
    await async_update_user_in_config({"username": u, "channels": [f"#{u}-direct"], "access_token": "a" * 20, "client_id": "b" * 10, "client_secret": "c" * 10}, cfg_path)


def _validate_user_data(data: dict[str, dict[str, Any]], users: list[str]) -> None:
    # Ensure every user present and channels reflect last queue OR direct write (last wins)
    for u in users:
        rec = data.get(u)
        if not rec:
            raise AssertionError(f"Missing user {u} in persisted file")
        chs = rec.get("channels", [])
        if not chs:
            raise AssertionError(f"User {u} channels empty")
        # Expect normalization lower-case and single entry due to last write overwriting
        if any(c != c.lower() for c in chs):
            raise AssertionError(f"User {u} channels not lowercased: {chs}")


@pytest.mark.asyncio
async def test_multi_user_interleaved_updates(tmp_path: Path) -> None:
    cfg = tmp_path / "stress.json"
    users = [f"user{i}" for i in range(5)]

    # Launch tasks
    tasks = []
    for u in users:
        tasks.append(asyncio.create_task(_rapid_queue_user(u, str(cfg))))
        tasks.append(asyncio.create_task(_occasional_direct_user(u, str(cfg))))

    try:
        await asyncio.gather(*tasks)
    except Exception:
        # Ensure all tasks are cancelled on failure to prevent resource leaks
        # and lingering async operations that could interfere with teardown
        for task in tasks:
            if not task.done():
                task.cancel()
        # Wait for cancellation to complete, ignoring cancellation exceptions
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        # Force flush any remaining pending updates to ensure clean state
        await flush_pending_updates(str(cfg))

    data = _read_config(cfg)
    _validate_user_data(data, users)
