from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from . import watcher_globals
from .constants import CONFIG_WRITE_DEBOUNCE
from .logger import logger


class ConfigRepository:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = str(path)
        self._last_checksum: str | None = None

    def load_raw(self) -> list[dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "users" in data:
                return data["users"]
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "username" in data:
                return [data]
            return []
        except FileNotFoundError:
            return []
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "config",
                "load_error",
                level=40,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []

    def _compute_checksum(self, users: list[dict[str, Any]]) -> str:
        h = hashlib.sha256()
        # Stable JSON representation
        payload = json.dumps(
            {"users": users}, sort_keys=True, separators=(",", ":")
        ).encode()
        h.update(payload)
        return h.hexdigest()

    def save_users(self, users: list[dict[str, Any]]) -> bool:
        try:
            try:
                watcher_globals.pause_config_watcher()
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "config",
                    "watcher_pause_failed",
                    level=10,
                    error=str(e),
                    error_type=type(e).__name__,
                )

            checksum = self._compute_checksum(users)
            if self._last_checksum == checksum:
                logger.log_event(
                    "config",
                    "save_skipped_checksum_match",
                    checksum=checksum,
                    user_count=len(users),
                )
                return False  # No write performed

            self._prepare_dir()
            self._atomic_write({"users": users})
            self._last_checksum = checksum
            time.sleep(CONFIG_WRITE_DEBOUNCE)
            return True
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "config",
                "save_failed",
                level=40,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
        finally:
            try:
                watcher_globals.resume_config_watcher()
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "config",
                    "watcher_resume_failed",
                    level=10,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    def _prepare_dir(self) -> None:
        config_dir = os.path.dirname(self.path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
            try:
                os.chmod(config_dir, 0o755)  # nosec B103
            except PermissionError:
                pass

    def _atomic_write(self, data: dict[str, Any]) -> None:
        config_path = Path(self.path)
        lock_path = config_path.with_suffix(".lock")
        temp_path: str | None = None
        try:
            with open(lock_path, "w", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=config_path.parent,
                    prefix=f".{config_path.name}.",
                    suffix=".tmp",
                    delete=False,
                    encoding="utf-8",
                ) as tmp:
                    json.dump(data, tmp, indent=2)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    temp_path = tmp.name
                os.chmod(temp_path, 0o600)
                os.rename(temp_path, self.path)
                logger.log_event("config", "save_atomic_success", config_file=self.path)
        except Exception as e:  # noqa: BLE001
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            logger.log_event(
                "config",
                "save_atomic_failed",
                level=40,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    def verify_readback(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            users_list = data.get("users", []) if isinstance(data, dict) else []
            logger.log_event(
                "config",
                "save_verification",
                user_count=len(users_list),
            )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "config",
                "save_atomic_failed",
                level=40,
                error=str(e),
                error_type=type(e).__name__,
            )
