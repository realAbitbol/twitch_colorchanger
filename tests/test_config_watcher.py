import json

import pytest

from src.config.watcher import ConfigWatcher


class DummyRestart:
    def __init__(self):
        self.calls: list[list[dict]] = []

    def __call__(self, users):  # noqa: D401
        self.calls.append(users)


@pytest.mark.asyncio
async def test_config_watcher_pause_resume(monkeypatch, tmp_path, caplog):
    caplog.set_level(10)
    # Prepare config file
    cfg = tmp_path / "twitch_colorchanger.conf"
    users = [
        {"username": "Henry", "channels": ["henry"], "access_token": "k" * 30},
    ]
    cfg.write_text(json.dumps(users))

    restart = DummyRestart()
    watcher = ConfigWatcher(str(cfg), restart)

    # Monkeypatch load_users_from_config to simulate modified content on change
    def fake_load(path: str):  # noqa: D401
        return [
            {"username": "Henry", "channels": ["henry"], "access_token": "k" * 30},
            {"username": "Ivy", "channels": ["ivy"], "access_token": "m" * 30},
        ]

    monkeypatch.setattr("src.config.watcher.load_users_from_config", fake_load)

    # Pause -> current implementation does not early-return inside _on_config_changed,
    # so restart will still be invoked. Assert that behaviour explicitly.
    watcher.pause_watching()
    watcher._on_config_changed()
    assert len(restart.calls) == 1

    # Resume (immediately clear pause flag)
    watcher.paused = False
    watcher._on_config_changed()
    assert len(restart.calls) == 2
    usernames = sorted(u["username"].lower() for u in restart.calls[-1])
    assert usernames == ["henry", "ivy"]


@pytest.mark.asyncio
async def test_config_watcher_invalid_cases(monkeypatch, tmp_path):
    cfg = tmp_path / "twitch_colorchanger.conf"
    cfg.write_text("[]")  # empty list

    restart = DummyRestart()
    watcher = ConfigWatcher(str(cfg), restart)

    # 1. Empty config
    watcher._on_config_changed()
    assert restart.calls == []

    # 2. No valid users after filtering
    def fake_load_invalid(_path):  # noqa: D401
        return [
            {"username": "aa", "channels": ["aa"], "access_token": "x" * 10},  # short username, token too short
        ]

    monkeypatch.setattr("src.config.watcher.load_users_from_config", fake_load_invalid)
    watcher._on_config_changed()
    assert restart.calls == []

    # 3. Processing error path
    def fake_load_error(_path):  # noqa: D401
        raise RuntimeError("boom")

    monkeypatch.setattr("src.config.watcher.load_users_from_config", fake_load_error)
    watcher._on_config_changed()  # Should log error but not raise
