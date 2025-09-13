from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.config.async_persistence import flush_pending_updates, queue_user_update


@pytest.mark.asyncio
async def test_user_lock_pruning_logs(monkeypatch, tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    # Reduce TTL to near-zero to force pruning after batch
    from src.config import async_persistence as ap

    monkeypatch.setattr(ap, "_LOCK_TTL_SECONDS", 0.0)
    cfg = tmp_path / "locks.json"

    caplog.set_level(20)

    await queue_user_update({"username": "Alpha", "channels": ["#a"]}, str(cfg))
    await queue_user_update({"username": "Beta", "channels": ["#b"]}, str(cfg))
    # Force flush; this will write and then prune (TTL zero)
    await flush_pending_updates(str(cfg))
    # Allow a tiny loop cycle
    await asyncio.sleep(0)

    msgs = [r.message for r in caplog.records]
    # Expect prune log referencing user_lock_prune template (remaining may vary) human text contains 'Pruned user locks'
    if not any("Pruned user locks" in m for m in msgs):
        raise AssertionError(f"Expected prune log message, got {msgs}")
