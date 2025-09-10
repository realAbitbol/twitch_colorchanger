from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_STATUS_FILE = os.environ.get(
    "TWITCH_HEALTH_STATUS_FILE",
    str(Path(tempfile.gettempdir()) / "twitch_colorchanger.health.json"),
)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def read_status(path: str | None = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_STATUS_FILE)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def write_status(updates: dict[str, Any], path: str | None = None) -> None:
    p = Path(path or DEFAULT_STATUS_FILE)
    existing = read_status(str(p))
    existing.update(updates)
    # ensure timestamp is present
    existing.setdefault("last_updated", time.time())
    try:
        _atomic_write(p, existing)
    except Exception:
        # best-effort; avoid raising from health writes
        try:
            # fallback non-atomic write
            with p.open("w", encoding="utf-8") as fh:
                json.dump(existing, fh)
        except Exception as e:  # noqa: BLE001
            try:
                # Minimal stderr fallback to avoid silent failures
                import sys as _sys

                _sys.stderr.write(f"health write fallback error: {e}\n")
            except Exception:
                ...
