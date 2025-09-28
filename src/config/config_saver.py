"""Configuration saving utilities."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .config_loader import ConfigLoader
from .config_utils import normalize_user_list
from .config_validator import ConfigValidator
from .model import UserConfig
from .repository import ConfigRepository


class ConfigSaver:
    """Manages saving configurations to files with checksum verification."""

    def __init__(
        self,
        loader: ConfigLoader | None = None,
        validator: ConfigValidator | None = None,
    ) -> None:
        """Initialize ConfigSaver.

        Args:
            loader: ConfigLoader instance for loading.
            validator: ConfigValidator instance for validation.
        """
        self.loader = loader or ConfigLoader()
        self.validator = validator or ConfigValidator()

    def save_users_to_config(self, users: Sequence[dict[str, Any]], config_file: str) -> None:
        """Save user configurations to the config file.

        Args:
            users: Sequence of user config dictionaries.
            config_file: Path to the configuration file.
        """
        normalized_users, changed = normalize_user_list(users)
        repo = ConfigRepository(config_file)
        wrote = repo.save_users(normalized_users)
        if wrote:
            repo.verify_readback()
        else:
            if changed:
                repo._last_checksum = None  # noqa: SLF001
                repo.save_users(normalized_users)
                repo.verify_readback()

    def update_user_in_config(self, user_config_dict: dict[str, Any], config_file: str) -> bool:
        """Update a user configuration in the config file.

        Args:
            user_config_dict: Dictionary containing user configuration data.
            config_file: Path to the configuration file.

        Returns:
            True if the update was successful, False otherwise.

        Raises:
            ValueError: If user config is invalid.
            RuntimeError: If update process fails.
            OSError: If file operations fail.
        """
        try:
            uc = UserConfig.from_dict(user_config_dict)
            changed = uc.normalize()
            if not uc.validate():
                return self._log_update_invalid(uc)
            users = self.loader.load_users_from_config(config_file)
            users, replaced = self._merge_user(users, uc)
            if not replaced:
                users.append(uc.to_dict())
            self.save_users_to_config(users, config_file)
            if changed:
                self._log_update_normalized(uc)
            return True
        except (ValueError, RuntimeError, OSError) as e:
            self._log_update_failed(e, user_config_dict)
            return False

    def _merge_user(
        self,
        users: list[dict[str, Any]], uc: UserConfig
    ) -> tuple[list[dict[str, Any]], bool]:
        """Merge a user config into the list of users.

        Args:
            users: List of existing user configs.
            uc: UserConfig instance to merge.

        Returns:
            Tuple of (updated_users, replaced) where replaced is True if an
            existing user was replaced.
        """
        uname = uc.username.lower()
        for i, existing in enumerate(users):
            if existing.get("username", "").strip().lower() == uname:
                merged = existing.copy()
                for k, v in uc.to_dict().items():
                    if v is not None:
                        merged[k] = v
                users[i] = {k: v for k, v in merged.items() if v is not None}
                return users, True
        return users, False

    def _log_update_invalid(self, uc: UserConfig) -> bool:
        """Log an invalid user update and return False.

        Args:
            uc: UserConfig instance that failed validation.

        Returns:
            False to indicate failure.
        """
        logging.warning(
            f"🚫 Rejected invalid user update username={uc.username or 'Unknown'}"
        )
        return False

    def _log_update_normalized(self, uc: UserConfig) -> None:
        """Log a normalized user update.

        Args:
            uc: UserConfig instance that was normalized.
        """
        logging.info(
            f"🛠️ User update normalized username={uc.username} channels={len(uc.channels)}"
        )

    def _log_update_failed(self, e: Exception, user_config_dict: dict[str, Any]) -> None:
        """Log a failed user update.

        Args:
            e: The exception that occurred.
            user_config_dict: The user config dictionary that caused the failure.
        """
        username = (
            user_config_dict.get("username") if isinstance(user_config_dict, dict) else None
        )
        logging.error(
            f"💥 Failed to update user in config: {username} - {type(e).__name__}: {e}"
        )
