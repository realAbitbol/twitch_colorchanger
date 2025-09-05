from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_sample_config(path: Path) -> None:
    # Minimal valid config file with one user (token placeholders sufficient length)
    sample = {
        "users": [
            {
                "username": "alice",
                "channels": ["#alice"],
                "access_token": "x" * 25,
                "refresh_token": "y" * 25,
            }
        ]
    }
    path.write_text(json.dumps(sample), encoding="utf-8")


def test_health_check_pass(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "conf.json"
    _write_sample_config(cfg)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    env["TWITCH_CONF_FILE"] = str(cfg)
    proc = subprocess.run(
        [sys.executable, "-m", "src.main", "--health-check"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Health check expected success exit code 0 got {proc.returncode} output={proc.stdout}")
    # Expect health_mode and health_pass messages (concise format shows human text only)
    if "Health check mode" not in proc.stdout or "Health check passed" not in proc.stdout:
        raise AssertionError(f"Expected health messages missing output={proc.stdout}")


def test_health_check_fail(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    # Missing config file should produce failure exit code 1
    cfg = tmp_path / "missing.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    env["TWITCH_CONF_FILE"] = str(cfg)
    proc = subprocess.run(
        [sys.executable, "-m", "src.main", "--health-check"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode == 0:
        raise AssertionError("Health check expected non-zero when config missing")
    # Failure path currently logs missing config + instruction rather than explicit health_fail event
    if "No configuration file" not in proc.stdout:
        raise AssertionError(f"Expected missing config message absent output={proc.stdout}")
