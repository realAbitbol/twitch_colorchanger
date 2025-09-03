from __future__ import annotations

import asyncio
import fcntl
import glob
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from constants import CONFIG_WRITE_DEBOUNCE
from logs.logger import logger

from . import globals as watcher_globals  # type: ignore


class ConfigRepository:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = str(path)
        self._last_checksum: str | None = None
        self._file_mtime: float | None = None
        self._file_size: int | None = None
        self._cached_users: list[dict[str, Any]] | None = None

    def load_raw(self) -> list[dict[str, Any]]:
        try:
            st = os.stat(self.path)
            mtime = st.st_mtime
            size = st.st_size
            if (
                self._cached_users is not None
                and self._file_mtime == mtime
                and self._file_size == size
            ):
                return self._cached_users

            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "users" in data:
                users = data["users"]
                self._cached_users = users
                self._file_mtime = mtime
                self._file_size = size
                return users
            if isinstance(data, list):
                self._cached_users = data
                self._file_mtime = mtime
                self._file_size = size
                return data
            if isinstance(data, dict) and "username" in data:
                self._cached_users = [data]
                self._file_mtime = mtime
                self._file_size = size
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
            # Non-blocking debounce if inside event loop; fallback to minimal sleep else
            try:
                loop = asyncio.get_running_loop()

                # Schedule a tiny asynchronous debounce without blocking caller
                async def _debounce():  # pragma: no cover (timing minor)
                    await asyncio.sleep(CONFIG_WRITE_DEBOUNCE)

                loop.create_task(_debounce())
            except RuntimeError:  # no running loop
                # Keep previous behavior but shorter to avoid blocking excessively
                time.sleep(min(CONFIG_WRITE_DEBOUNCE, 0.05))
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
            # Ensure directory is at most rwx for owner and rx for group/others (not world-writable)
            try:
                current_mode = stat.S_IMODE(os.lstat(config_dir).st_mode)
                desired_mode = 0o755
                if current_mode != desired_mode:
                    os.chmod(config_dir, desired_mode)
            except PermissionError:
                pass
            except FileNotFoundError:
                pass

    def _atomic_write(self, data: dict[str, Any]) -> None:
        config_path = Path(self.path)
        lock_path = config_path.with_suffix(".lock")
        temp_path: str | None = None
        try:
            with open(lock_path, "w", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                # Rotating backup (extracted to helper to reduce complexity)
                self._create_backup(config_path)
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

    def _create_backup(self, config_path: Path) -> None:
        if not (config_path.exists() and config_path.is_file()):
            return
        try:  # pragma: no cover - filesystem timing nuances
            backup_dir = config_path.parent
            timestamp = int(time.time())
            backup_name = backup_dir / f"{config_path.name}.bak.{timestamp}"
            shutil.copy2(config_path, backup_name)
            logger.log_event(
                "config",
                "backup_created",
                backup=str(backup_name.name),
            )
            backups = sorted(
                glob.glob(str(backup_dir / f"{config_path.name}.bak.*")),
                reverse=True,
            )
            for old in backups[3:]:
                try:
                    os.unlink(old)
                except OSError:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "config",
                "backup_failed",
                level=10,
                error=str(e),
            )

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
