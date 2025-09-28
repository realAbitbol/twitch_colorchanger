"""Core configuration management utilities (moved from top-level config.py)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .config_loader import ConfigLoader
from .config_saver import ConfigSaver
from .model import UserConfig
from .token_setup_coordinator import TokenSetupCoordinator


def load_users_from_config(config_file: str) -> list[dict[str, Any]]:
    """Load user configurations from the config file.

    Args:
        config_file: Path to the configuration file.

    Returns:
        List of user config dictionaries.
    """
    loader = ConfigLoader()
    return loader.load_users_from_config(config_file)


def save_users_to_config(users: Sequence[dict[str, Any]], config_file: str) -> None:
    """Save user configurations to the config file.

    Args:
        users: Sequence of user config dictionaries.
        config_file: Path to the configuration file.
    """
    saver = ConfigSaver()
    saver.save_users_to_config(users, config_file)


def update_user_in_config(user_config_dict: dict[str, Any], config_file: str) -> bool:
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
    saver = ConfigSaver()
    return saver.update_user_in_config(user_config_dict, config_file)






def get_configuration() -> list[UserConfig]:
    """Load and validate user configurations from the config file.

    Returns:
        List of valid UserConfig instances.

    Raises:
        SystemExit: If no config file or no valid users found.
    """
    loader = ConfigLoader()
    return loader.get_configuration()


def print_config_summary(users: Sequence[UserConfig]) -> None:
    """Print a summary of user configurations.

    Args:
        users: Sequence of UserConfig instances.
    """
    logging.debug(f"📊 Configuration summary (users={len(users)})")
    for _i, user in enumerate(users, 1):
        username = user.username
        logging.debug(f"👤 User summary {username}")


def normalize_user_channels(
    users: Sequence[UserConfig], config_file: str
) -> tuple[list[UserConfig], bool]:
    """Normalize user channels and save if changed.

    Args:
        users: Sequence of UserConfig instances.
        config_file: Path to the configuration file.

    Returns:
        Tuple of (normalized_users, any_changes).
    """
    normalized_users: list[UserConfig] = []
    any_changes = False
    for uc in users:
        if uc.normalize():
            any_changes = True
        normalized_users.append(uc)
    if any_changes:
        try:
            user_dicts = [uc.to_dict() for uc in normalized_users]
            save_users_to_config(user_dicts, config_file)
            logging.info("💾 Channel normalization saved")
        except (OSError, ValueError, RuntimeError) as e:
            logging.error(f"💥 Failed saving normalization: {type(e).__name__}")
    return normalized_users, any_changes


async def setup_missing_tokens(
    users: list[UserConfig], config_file: str
) -> list[UserConfig]:
    """Set up missing tokens for users.

    Args:
        users: List of UserConfig instances.
        config_file: Path to the configuration file.

    Returns:
        List of updated UserConfig instances.

    Raises:
        aiohttp.ClientError: If network requests fail.
        ValueError: If token provisioning fails.
        RuntimeError: If token setup process fails.
    """
    coordinator = TokenSetupCoordinator()
    return await coordinator.setup_missing_tokens(users, config_file)


