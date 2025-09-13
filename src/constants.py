"""
Configuration constants for the Twitch Color Changer Bot

This module contains all configurable constants used throughout the application.
Each constant can be overridden by setting an environment variable with the same name.
"""

import os


def _get_env_int(name: str, default: int) -> int:
    """Retrieve an integer value from an environment variable.

    Attempts to parse the environment variable as an integer. If the variable
    is not set or cannot be parsed, logs a warning and returns the default value.

    Args:
        name: The name of the environment variable to read.
        default: The default integer value to return if parsing fails.

    Returns:
        The parsed integer value from the environment, or the default if unavailable.
    """
    value = os.getenv(name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            print(
                f"Warning: Invalid integer value for {name}='{value}', using default {default}"
            )
    return default


def _get_env_float(name: str, default: float) -> float:
    """Retrieve a float value from an environment variable.

    Attempts to parse the environment variable as a float. If the variable
    is not set or cannot be parsed, logs a warning and returns the default value.

    Args:
        name: The name of the environment variable to read.
        default: The default float value to return if parsing fails.

    Returns:
        The parsed float value from the environment, or the default if unavailable.
    """
    value = os.getenv(name)
    if value is not None:
        try:
            return float(value)
        except ValueError:
            print(
                f"Warning: Invalid float value for {name}='{value}', using default {default}"
            )
    return default


## Removed unused CONFIG_SAVE_TIMEOUT (async save no longer blocks)  # noqa: ERA001

# Token expiry & refresh thresholds (unify scattered literals: 3600s & 300s)
TOKEN_REFRESH_THRESHOLD_SECONDS = _get_env_int(
    "TOKEN_REFRESH_THRESHOLD_SECONDS", 3600
)  # Refresh when <= this many seconds remain (1h default)
TOKEN_REFRESH_SAFETY_BUFFER_SECONDS = _get_env_int(
    "TOKEN_REFRESH_SAFETY_BUFFER_SECONDS", 300
)  # Subtracted from expires_in to schedule earlier refresh

# Token manager scheduling/validation intervals
TOKEN_MANAGER_VALIDATION_MIN_INTERVAL = _get_env_int(
    "TOKEN_MANAGER_VALIDATION_MIN_INTERVAL", 30
)  # Minimum seconds between per-user validation attempts
TOKEN_MANAGER_BACKGROUND_BASE_SLEEP = _get_env_int(
    "TOKEN_MANAGER_BACKGROUND_BASE_SLEEP", 60
)  # Base seconds between proactive refresh loop iterations
TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL = _get_env_int(
    "TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL", 1800
)  # Seconds between periodic remote validations (default 30 min)
