from __future__ import annotations

import fcntl
import glob
import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any


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
                raw_users = data["users"]  # expected list[dict[str, Any]]
                if not isinstance(raw_users, list):
                    return []
                # Runtime validation: ensure list elements are dict-like
                users_list: list[dict[str, Any]] = [
                    u for u in raw_users if isinstance(u, dict)
                ]
                self._cached_users = users_list
                self._file_mtime = mtime
                self._file_size = size
                return users_list
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
            logging.error(f"Configuration load error: {e}")
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
        checksum = self._compute_checksum(users)
        if self._last_checksum == checksum:
            logging.info(f"Skipped save (checksum match) users={len(users)}")
            return False  # No write performed

        self._prepare_dir()
        self._atomic_write({"users": users})
        self._last_checksum = checksum
        return True

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
                logging.info("💾 Config saved atomically")
        except Exception as e:  # noqa: BLE001
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            logging.error(f"💥 Atomic config save failed: {type(e).__name__}")
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
            logging.info("🗄️ Config backup created")
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
            logging.debug(f"💥 Config backup failed: {str(e)}")

    def verify_readback(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            users_list = data.get("users", []) if isinstance(data, dict) else []
            logging.info(f"🔍 Verification read user_count={len(users_list)}")
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 Atomic config save failed: {type(e).__name__}")
