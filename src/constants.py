"""
Configuration constants for the Twitch Color Changer Bot

This module contains all configurable constants used throughout the application.
Each constant can be overridden by setting an environment variable with the same name.
"""

import os


def _get_env_int(name: str, default: int) -> int:
    """Get an integer value from environment variable or return default."""
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
    """Get a float value from environment variable or return default."""
    value = os.getenv(name)
    if value is not None:
        try:
            return float(value)
        except ValueError:
            print(
                f"Warning: Invalid float value for {name}='{value}', using default {default}"
            )
    return default


# IRC connection timing
PING_EXPECTED_INTERVAL = _get_env_int(
    "PING_EXPECTED_INTERVAL", 600
)  # IRC server ping expected every 10 min
SERVER_ACTIVITY_TIMEOUT = _get_env_int(
    "SERVER_ACTIVITY_TIMEOUT", 300
)  # 5 min without any server activity
CHANNEL_JOIN_TIMEOUT = _get_env_int(
    "CHANNEL_JOIN_TIMEOUT", 30
)  # Max wait for JOIN confirmation
MAX_JOIN_ATTEMPTS = _get_env_int(
    "MAX_JOIN_ATTEMPTS", 2
)  # Maximum join attempts before giving up
RECONNECT_DELAY = _get_env_int("RECONNECT_DELAY", 2)  # Base delay before reconnection

# Health monitoring timing
HEALTH_MONITOR_INTERVAL = _get_env_int(
    "HEALTH_MONITOR_INTERVAL", 300
)  # Check bot health every 5 minutes
TASK_WATCHDOG_INTERVAL = _get_env_int(
    "TASK_WATCHDOG_INTERVAL", 120
)  # Check specific task health every 2 minutes
CONNECTION_RETRY_TIMEOUT = _get_env_int(
    "CONNECTION_RETRY_TIMEOUT", 600
)  # Give up on connection after 10 minutes

# Configuration management
RELOAD_WATCH_DELAY = _get_env_float(
    "RELOAD_WATCH_DELAY", 2.0
)  # Delay after config reload before resuming watch
CONFIG_SAVE_TIMEOUT = _get_env_float(
    "CONFIG_SAVE_TIMEOUT", 10.0
)  # Max time to wait for config save completion

# File operations
CONFIG_WRITE_DEBOUNCE = _get_env_float(
    "CONFIG_WRITE_DEBOUNCE", 0.5
)  # Delay after save for watcher resume

# Rate limiting defaults
DEFAULT_BUCKET_LIMIT = _get_env_int("DEFAULT_BUCKET_LIMIT", 800)
RATE_LIMIT_SAFETY_BUFFER = _get_env_int("RATE_LIMIT_SAFETY_BUFFER", 5)
STALE_BUCKET_AGE = _get_env_int("STALE_BUCKET_AGE", 60)

# Async IRC configuration
ASYNC_IRC_READ_TIMEOUT = _get_env_float(
    "ASYNC_IRC_READ_TIMEOUT", 1.0
)  # Read timeout for async IRC operations (seconds)
ASYNC_IRC_CONNECT_TIMEOUT = _get_env_float(
    "ASYNC_IRC_CONNECT_TIMEOUT", 15.0
)  # Connection timeout for async IRC (seconds)
ASYNC_IRC_JOIN_TIMEOUT = _get_env_float(
    "ASYNC_IRC_JOIN_TIMEOUT", 30.0
)  # Channel join timeout for async IRC (seconds)
ASYNC_IRC_RECONNECT_TIMEOUT = _get_env_float(
    "ASYNC_IRC_RECONNECT_TIMEOUT", 30.0
)  # Reconnection timeout for async IRC (seconds)

# Exponential backoff parameters
BACKOFF_BASE_DELAY = _get_env_float(
    "BACKOFF_BASE_DELAY", 1.0
)  # Base delay for exponential backoff (seconds)
BACKOFF_MAX_DELAY = _get_env_float(
    "BACKOFF_MAX_DELAY", 300.0
)  # Maximum delay for exponential backoff (5 minutes)
BACKOFF_MULTIPLIER = _get_env_float(
    "BACKOFF_MULTIPLIER", 2.0
)  # Multiplier for exponential backoff
BACKOFF_JITTER_FACTOR = _get_env_float(
    "BACKOFF_JITTER_FACTOR", 0.1
)  # Jitter factor to avoid thundering herd

# Network partition detection
NETWORK_PARTITION_THRESHOLD = _get_env_int(
    "NETWORK_PARTITION_THRESHOLD", 900
)  # 15 minutes of no connectivity before declaring partition
PARTIAL_CONNECTIVITY_THRESHOLD = _get_env_int(
    "PARTIAL_CONNECTIVITY_THRESHOLD", 180
)  # 3 minutes for partial connectivity detection
