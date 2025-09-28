"""Configuration loading utilities."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from .config_validator import ConfigValidator
from .model import UserConfig
from .repository import ConfigRepository


class ConfigLoader:
    """Handles loading user configurations from files and raw data processing."""

    def __init__(self, validator: ConfigValidator | None = None) -> None:
        """Initialize ConfigLoader.

        Args:
            validator: ConfigValidator instance for validation.
        """
        self.validator = validator or ConfigValidator()

    def load_users_from_config(self, config_file: str) -> list[dict[str, Any]]:
        """Load user configurations from the config file.

        Args:
            config_file: Path to the configuration file.

        Returns:
            List of user config dictionaries.
        """
        repo = ConfigRepository(config_file)
        return repo.load_raw()

    def get_configuration(self) -> list[UserConfig]:
        """Load and validate user configurations from the config file.

        Returns:
            List of valid UserConfig instances.

        Raises:
            SystemExit: If no config file or no valid users found.
        """
        config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
        users = self.load_users_from_config(config_file)
        if not users:
            logging.error("📁 No configuration file found")
            logging.error("📄 Instruction emitted for creating config file")
            sys.exit(1)
        valid_users = self.validator.validate_and_filter_users_to_dataclasses(users)
        if not valid_users:
            logging.error("⚠️ No valid user configurations found")
            sys.exit(1)
        logging.info(f"✅ Valid user configurations found count={len(valid_users)}")
        return valid_users
