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

# Color-related constants
COLOR_RANDOM_HEX_MAX_ATTEMPTS = _get_env_int(
    "COLOR_RANDOM_HEX_MAX_ATTEMPTS", 10
)  # Max attempts to generate unique random hex color
COLOR_MAX_HUE = _get_env_int("COLOR_MAX_HUE", 359)  # Maximum hue value (0-359 degrees)
COLOR_MIN_SATURATION = _get_env_int(
    "COLOR_MIN_SATURATION", 60
)  # Minimum saturation percentage
COLOR_MAX_SATURATION = _get_env_int(
    "COLOR_MAX_SATURATION", 100
)  # Maximum saturation percentage
COLOR_MIN_LIGHTNESS = _get_env_int(
    "COLOR_MIN_LIGHTNESS", 35
)  # Minimum lightness percentage
COLOR_MAX_LIGHTNESS = _get_env_int(
    "COLOR_MAX_LIGHTNESS", 75
)  # Maximum lightness percentage
COLOR_HUE_SECTOR_SIZE = _get_env_int(
    "COLOR_HUE_SECTOR_SIZE", 60
)  # Hue sector size for HSL to RGB conversion
COLOR_RGB_MAX_VALUE = _get_env_int(
    "COLOR_RGB_MAX_VALUE", 255
)  # Maximum RGB component value

# Network/HTTP constants
HTTP_REQUEST_TIMEOUT_SECONDS = _get_env_int(
    "HTTP_REQUEST_TIMEOUT_SECONDS", 30
)  # Default HTTP request timeout
WEBSOCKET_MESSAGE_TIMEOUT_SECONDS = _get_env_int(
    "WEBSOCKET_MESSAGE_TIMEOUT_SECONDS", 10
)  # WebSocket message timeout

# Retry/backoff constants
DEFAULT_MAX_RETRY_ATTEMPTS = _get_env_int(
    "DEFAULT_MAX_RETRY_ATTEMPTS", 6
)  # Default maximum retry attempts
RETRY_BACKOFF_MULTIPLIER = _get_env_int(
    "RETRY_BACKOFF_MULTIPLIER", 1
)  # Exponential backoff multiplier
RETRY_MAX_BACKOFF_SECONDS = _get_env_int(
    "RETRY_MAX_BACKOFF_SECONDS", 60
)  # Maximum backoff time in seconds
OPERATION_MAX_ATTEMPTS = _get_env_int(
    "OPERATION_MAX_ATTEMPTS", 3
)  # Max attempts for specific operations
RECONNECT_MAX_ATTEMPTS = _get_env_int(
    "RECONNECT_MAX_ATTEMPTS", 10
)  # Maximum reconnection attempts
INITIAL_BACKOFF_SECONDS = _get_env_int(
    "INITIAL_BACKOFF_SECONDS", 1
)  # Initial backoff time in seconds
MAX_BACKOFF_SECONDS = _get_env_int(
    "MAX_BACKOFF_SECONDS", 30
)  # Maximum backoff time in seconds

# EventSub/WebSocket constants
WEBSOCKET_HEARTBEAT_SECONDS = _get_env_int(
    "WEBSOCKET_HEARTBEAT_SECONDS", 30
)  # WebSocket heartbeat interval
EVENTSUB_SUB_CHECK_INTERVAL_SECONDS = _get_env_int(
    "EVENTSUB_SUB_CHECK_INTERVAL_SECONDS", 600
)  # Subscription check interval (10 min)
EVENTSUB_STALE_THRESHOLD_SECONDS = _get_env_int(
    "EVENTSUB_STALE_THRESHOLD_SECONDS", 70
)  # Stale connection threshold
EVENTSUB_MAX_BACKOFF_SECONDS = _get_env_int(
    "EVENTSUB_MAX_BACKOFF_SECONDS", 30
)  # Maximum EventSub backoff
EVENTSUB_FAST_AUDIT_MIN_SECONDS = _get_env_int(
    "EVENTSUB_FAST_AUDIT_MIN_SECONDS", 60
)  # Fast audit minimum delay
EVENTSUB_FAST_AUDIT_MAX_SECONDS = _get_env_int(
    "EVENTSUB_FAST_AUDIT_MAX_SECONDS", 120
)  # Fast audit maximum delay
JITTER_RESOLUTION = _get_env_int(
    "JITTER_RESOLUTION", 1_000_000
)  # Jitter calculation resolution
WEBSOCKET_CLOSE_TOKEN_REFRESH = _get_env_int(
    "WEBSOCKET_CLOSE_TOKEN_REFRESH", 4001
)  # Close code for token refresh
WEBSOCKET_CLOSE_SESSION_STALE = _get_env_int(
    "WEBSOCKET_CLOSE_SESSION_STALE", 4007
)  # Close code for session stale
EVENTSUB_CONSECUTIVE_401_THRESHOLD = _get_env_int(
    "EVENTSUB_CONSECUTIVE_401_THRESHOLD", 2
)  # Consecutive 401 threshold
EVENTSUB_RECONNECT_DELAY_SECONDS = _get_env_int(
    "EVENTSUB_RECONNECT_DELAY_SECONDS", 1
)  # Reconnect delay
EVENTSUB_JITTER_FACTOR = _get_env_float(
    "EVENTSUB_JITTER_FACTOR", 0.25
)  # Jitter factor for backoff

# Configuration/cache constants
COLOR_CACHE_TTL_SECONDS = _get_env_int("COLOR_CACHE_TTL_SECONDS", 30)  # Color cache TTL
CONFIG_DEBOUNCE_SECONDS = _get_env_float(
    "CONFIG_DEBOUNCE_SECONDS", 0.25
)  # Config save debounce delay
USER_LOCK_TTL_HOURS = _get_env_int("USER_LOCK_TTL_HOURS", 1)  # User lock TTL in hours
USER_LOCK_TTL_SECONDS = USER_LOCK_TTL_HOURS * 3600  # User lock TTL in seconds
CONFIG_MAX_FAILURES_WARNING = _get_env_int(
    "CONFIG_MAX_FAILURES_WARNING", 3
)  # Max failures before warning
CONFIG_SAVE_MAX_RETRIES = _get_env_int(
    "CONFIG_SAVE_MAX_RETRIES", 3
)  # Max config save retries
CONFIG_SAVE_RETRY_DELAY_SECONDS = _get_env_float(
    "CONFIG_SAVE_RETRY_DELAY_SECONDS", 0.1
)  # Config save retry delay

# Authentication/token constants
DEVICE_FLOW_POLL_INTERVAL_SECONDS = _get_env_int(
    "DEVICE_FLOW_POLL_INTERVAL_SECONDS", 5
)  # Device flow poll interval
DEVICE_FLOW_POLL_ADJUSTMENT = _get_env_int(
    "DEVICE_FLOW_POLL_ADJUSTMENT", 10
)  # Poll interval adjustment
DEVICE_FLOW_LOG_INTERVAL_DIVISOR = _get_env_int(
    "DEVICE_FLOW_LOG_INTERVAL_DIVISOR", 6
)  # Log interval divisor
MIN_ACCESS_TOKEN_LENGTH = _get_env_int(
    "MIN_ACCESS_TOKEN_LENGTH", 20
)  # Minimum access token length
MIN_CLIENT_CREDENTIAL_LENGTH = _get_env_int(
    "MIN_CLIENT_CREDENTIAL_LENGTH", 10
)  # Minimum client credential length
TOKEN_MAX_FORCED_UNKNOWN_ATTEMPTS = _get_env_int(
    "TOKEN_MAX_FORCED_UNKNOWN_ATTEMPTS", 3
)  # Max forced unknown attempts
TOKEN_LOW_THRESHOLD_SECONDS = _get_env_int(
    "TOKEN_LOW_THRESHOLD_SECONDS", 900
)  # Low token threshold (15 min)
TOKEN_MEDIUM_THRESHOLD_SECONDS = _get_env_int(
    "TOKEN_MEDIUM_THRESHOLD_SECONDS", 3600
)  # Medium token threshold (1h)
TOKEN_HIGH_THRESHOLD_MULTIPLIER = _get_env_int(
    "TOKEN_HIGH_THRESHOLD_MULTIPLIER", 2
)  # High token threshold multiplier

# Bot/core constants
LISTENER_TASK_TIMEOUT_SECONDS = _get_env_int(
    "LISTENER_TASK_TIMEOUT_SECONDS", 2
)  # Listener task timeout
BOT_STOP_DELAY_SECONDS = _get_env_float("BOT_STOP_DELAY_SECONDS", 0.1)  # Bot stop delay
BOT_STARTUP_DELAY_SECONDS = _get_env_int(
    "BOT_STARTUP_DELAY_SECONDS", 1
)  # Bot startup delay
MANAGER_LOOP_SLEEP_SECONDS = _get_env_int(
    "MANAGER_LOOP_SLEEP_SECONDS", 1
)  # Manager loop sleep

# Utility/helper constants
HEX_SHORT_LENGTH = _get_env_int("HEX_SHORT_LENGTH", 3)  # Short hex color length
HEX_FULL_LENGTH = _get_env_int("HEX_FULL_LENGTH", 6)  # Full hex color length
