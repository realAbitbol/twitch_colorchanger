"""Configuration package exports.

Unified access point for configuration repository/model and
the higher-level procedural API (migrated from former top-level config.py).
"""

from .core import (  # noqa: F401
    get_configuration,
    load_users_from_config,
    normalize_user_channels,
    print_config_summary,
    save_users_to_config,
    setup_missing_tokens,
    update_user_in_config,
)
from .model import UserConfig
from .repository import ConfigRepository

__all__ = [
    "ConfigRepository",
    "UserConfig",
    "get_configuration",
    "load_users_from_config",
    "save_users_to_config",
    "update_user_in_config",
    "print_config_summary",
    "normalize_user_channels",
    "setup_missing_tokens",
]
