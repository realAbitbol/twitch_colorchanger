import os

import pytest

# Only run if watchdog available
try:
    import watchdog  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
    pytest.skip("watchdog not installed", allow_module_level=True)

from src.config.watcher import create_config_watcher  # noqa: E402


class DummyHandler:
    def __init__(self):
        self.called = False
    async def on_change(self):  # signature expected by watcher
        import asyncio
        self.called = True
        await asyncio.sleep(0)

@pytest.mark.asyncio
async def test_create_and_close_watcher(tmp_path):
    cfg = tmp_path / "conf.json"
    cfg.write_text("{}", encoding="utf-8")
    handler = DummyHandler()
    watcher = await create_config_watcher(str(cfg), handler.on_change)
    # touch file to trigger; allow short time for debounce
    os.utime(cfg, None)
    watcher.stop()  # ensure clean shutdown (no exception)
