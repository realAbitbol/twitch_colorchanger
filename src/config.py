"""
Configuration management for the Twitch Color Changer bot
"""

import fcntl
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from . import (
    token_validator,  # Standalone validator module (no circular import)
    watcher_globals,  # Always available within package
)
from .config_validator import get_valid_users
from .config_validator import validate_user_config as validate_user
from .constants import CONFIG_WRITE_DEBOUNCE
from .device_flow import DeviceCodeFlow
from .logger import logger

# Legacy print_log removed after migration; structured logger used throughout

# Constants for repeated messages


def load_users_from_config(config_file):
    """Load users from config file"""
    try:
        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)
            # Support both new multi-user format and legacy single-user format
            if isinstance(data, dict) and "users" in data:
                return data["users"]
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "username" in data:
                # Legacy single-user format, convert to multi-user
                return [data]
            return []
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.log_event(
            "config",
            "load_error",
            level=logging.ERROR,
            error=str(e),
            error_type=type(e).__name__,
        )
        return []


def _setup_config_directory(config_file):
    """Set up config directory with proper permissions"""
    config_dir = os.path.dirname(config_file)
    if config_dir and not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        # Try to set directory permissions if possible
        try:
            # Using 755 for cross-platform readability; not sensitive content
            # stored here. # nosec B103
            os.chmod(config_dir, 0o755)  # nosec B103
        except PermissionError:
            pass  # Ignore permission errors on directories


def _fix_docker_ownership(config_dir, config_file):
    """Fix ownership for Docker environments running as non-root"""
    if os.path.exists(config_dir) and os.geteuid() != 0:
        try:
            # Try to change ownership of the config directory to current user
            current_uid = os.getuid()
            current_gid = os.getgid()
            os.chown(config_dir, current_uid, current_gid)
            # Also try to change ownership of existing config file
            if os.path.exists(config_file):
                os.chown(config_file, current_uid, current_gid)
        except OSError:
            pass  # Ignore if we can't change ownership (e.g., no permission)


def _set_file_permissions(config_file):
    """Set appropriate file permissions"""
    if os.path.exists(config_file):
        try:
            os.chmod(config_file, 0o644)
        except PermissionError:
            pass  # Ignore permission errors on existing files


def _log_save_operation(users, config_file):
    """Log the save operation details (debug level)."""
    logger.log_event(
        "config",
        "save_operation_start",
        level=logging.DEBUG,
        user_count=len(users),
        config_file=config_file,
    )
    for i, user in enumerate(users, 1):
        logger.log_event(
            "config",
            "save_user_detail",
            level=logging.DEBUG,
            index=i,
            username=user.get("username"),
            is_prime_or_turbo=user.get("is_prime_or_turbo", "MISSING_FIELD"),
        )


def _log_debug_data(save_data):
    """Log debug information about the data being saved."""
    preview = json.dumps(save_data, separators=(",", ":"))
    if len(preview) > 500:
        preview = preview[:497] + "..."
    logger.log_event(
        "config",
        "save_json_preview",
        level=logging.DEBUG,
        length=len(preview),
        data=preview,
    )


def _verify_saved_data(config_file):
    """Verify that the data was saved correctly (debug events)."""
    try:
        with open(config_file, encoding="utf-8") as f:
            verification_data = json.load(f)
        users_list = verification_data.get("users", [])
        logger.log_event(
            "config",
            "save_verification",
            level=logging.DEBUG,
            user_count=len(users_list),
        )
        for i, user in enumerate(users_list, 1):
            logger.log_event(
                "config",
                "save_verification_user",
                level=logging.DEBUG,
                index=i,
                username=user.get("username", "NO_USERNAME"),
                is_prime_or_turbo=user.get("is_prime_or_turbo", "MISSING_FIELD"),
            )
    except Exception as verify_error:
        logger.log_event(
            "config",
            "save_atomic_failed",
            level=logging.ERROR,
            error_type=type(verify_error).__name__,
            error=str(verify_error),
        )


def save_users_to_config(users, config_file):
    """Save users to config file"""
    try:
        # Pause watcher during bot-initiated changes
        try:
            watcher_globals.pause_config_watcher()
        except Exception:  # nosec B110
            pass  # Watcher not initialized - expected in some contexts

        # Ensure all users have is_prime_or_turbo field before saving
        for user in users:
            if "is_prime_or_turbo" not in user:
                user["is_prime_or_turbo"] = True  # Default value
                logger.log_event(
                    "config",
                    "added_missing_is_prime_or_turbo",
                    level=logging.DEBUG,
                    username=user.get("username", "Unknown"),
                    value=user["is_prime_or_turbo"],
                )

        # Set up directory and permissions
        _setup_config_directory(config_file)
        config_dir = os.path.dirname(config_file)
        _fix_docker_ownership(config_dir, config_file)
        _set_file_permissions(config_file)

        # Log operation
        _log_save_operation(users, config_file)

        # Prepare and save data
        save_data = {"users": users}
        _log_debug_data(save_data)

        # ATOMIC SAVE WITH FILE LOCKING
        config_path = Path(config_file)
        lock_file = None
        temp_path = None

        try:
            # 1. Create lock file for cross-process coordination
            lock_file_path = config_path.with_suffix(".lock")
            with open(lock_file_path, "w", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # Exclusive lock

                # 2. Write to temporary file in same directory (ensures atomic rename)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=config_path.parent,
                    prefix=f".{config_path.name}.",
                    suffix=".tmp",
                    delete=False,
                    encoding="utf-8",
                ) as temp_file:
                    json.dump(save_data, temp_file, indent=2)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())  # Force write to disk
                    temp_path = temp_file.name

                # 3. Set secure permissions
                os.chmod(temp_path, 0o600)

                # 4. Atomic rename (the critical moment)
                os.rename(temp_path, config_file)

                logger.log_event(
                    "config",
                    "save_atomic_success",
                    config_file=config_file,
                )

        except Exception as save_error:
            # Cleanup temp file on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            logger.log_event(
                "config",
                "save_atomic_failed",
                level=logging.ERROR,
                error=str(save_error),
                error_type=type(save_error).__name__,
            )
            raise

        finally:
            # Cleanup lock file
            try:
                os.unlink(lock_file_path)
            except OSError:
                pass

        # Verify the save
        _verify_saved_data(config_file)

        # Add delay before resuming watcher to avoid detecting our own change
        time.sleep(CONFIG_WRITE_DEBOUNCE)

    except Exception as e:
        logger.log_event(
            "config",
            "save_failed",
            level=logging.ERROR,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    finally:
        # Always resume watcher
        try:
            watcher_globals.resume_config_watcher()
        except Exception:  # nosec B110
            pass  # Watcher not initialized - expected in some contexts


def update_user_in_config(user_config, config_file):
    """Update a specific user's configuration in the config file"""
    try:
        users = load_users_from_config(config_file)
        updated = False

        # Ensure the user_config has is_prime_or_turbo field
        if "is_prime_or_turbo" not in user_config:
            user_config["is_prime_or_turbo"] = True  # Default value
            logger.log_event(
                "config",
                "added_missing_is_prime_or_turbo",
                level=logging.DEBUG,
                username=user_config.get("username", "Unknown"),
                value=user_config["is_prime_or_turbo"],
            )

        # Find and update existing user
        for i, user in enumerate(users):
            if user.get("username") == user_config["username"]:
                # Create a new config with proper field order
                merged_config = {
                    "username": user_config.get("username", user.get("username")),
                    "client_id": user_config.get("client_id", user.get("client_id")),
                    "client_secret": user_config.get(
                        "client_secret", user.get("client_secret")
                    ),
                    "access_token": user_config.get(
                        "access_token", user.get("access_token")
                    ),
                    "refresh_token": user_config.get(
                        "refresh_token", user.get("refresh_token")
                    ),
                    "channels": user_config.get("channels", user.get("channels", [])),
                    "is_prime_or_turbo": user_config.get(
                        "is_prime_or_turbo", user.get("is_prime_or_turbo", True)
                    ),
                }
                # Remove any None values to keep config clean
                merged_config = {
                    k: v for k, v in merged_config.items() if v is not None
                }
                users[i] = merged_config
                updated = True
                break

        # If user not found, add them
        if not updated:
            users.append(user_config)

        save_users_to_config(users, config_file)
        return True
    except Exception as e:
        logger.log_event(
            "config",
            "update_user_failed",
            level=logging.ERROR,
            error=str(e),
            error_type=type(e).__name__,
            username=user_config.get("username"),
        )
        return False


def disable_random_colors_for_user(username, config_file):
    """Disable random colors for a specific user due to Turbo/Prime requirement"""
    try:
        users = load_users_from_config(config_file)
        user_found = False
        for user in users:
            if user.get("username") == username:
                user_found = True
                if user.get("is_prime_or_turbo") is not False:
                    user["is_prime_or_turbo"] = False
                    logger.log_event(
                        "config",
                        "random_colors_disabled",
                        username=username,
                    )
                break
        if not user_found:
            logger.log_event(
                "config",
                "random_colors_user_not_found",
                level=logging.WARNING,
                username=username,
            )
            return False
        save_users_to_config(users, config_file)
        return True
    except Exception as e:
        logger.log_event(
            "config",
            "disable_random_colors_failed",
            level=logging.ERROR,
            username=username,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


def validate_user_config(user_config):
    """Validate that user configuration has required fields - Simplified version"""
    return validate_user(user_config)


def get_configuration():
    """Get configuration from config file only"""
    config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")

    # Load configuration from file
    users = load_users_from_config(config_file)

    if not users:
        logger.log_event(
            "config", "no_config_file", level=logging.ERROR, config_file=config_file
        )
        logger.log_event(
            "config",
            "no_config_file_instruction",
            level=logging.ERROR,
            sample="twitch_colorchanger.conf.sample",
        )
        sys.exit(1)

    # Validate users
    valid_users = get_valid_users(users)

    if not valid_users:
        logger.log_event(
            "config", "no_valid_users", level=logging.ERROR, config_file=config_file
        )
        sys.exit(1)

    logger.log_event(
        "config",
        "valid_users_found",
        user_count=len(valid_users),
    )
    return valid_users


def print_config_summary(users):
    """Log a summary of the loaded configuration"""
    logger.log_event("config", "summary", user_count=len(users))
    for i, user in enumerate(users, 1):
        logger.log_event(
            "config",
            "summary_user",
            index=i,
            username=user.get("username"),
            channel_count=len(user.get("channels", [])),
            channels=",".join(user.get("channels", [])),
            is_prime_or_turbo=user.get("is_prime_or_turbo", True),
            has_refresh_token=bool(user.get("refresh_token")),
        )


def normalize_channels(channels):
    """
    Normalize channel list: lowercase, remove #, sort, and deduplicate

    Args:
        channels: List of channel names

    Returns:
        Tuple of (normalized_channels, was_changed)
    """
    if not isinstance(channels, list):
        return [], True

    # Normalize: lowercase, remove #, deduplicate, and sort
    normalized = sorted(
        dict.fromkeys(
            ch.lower().strip().lstrip("#") for ch in channels if ch and ch.strip()
        )
    )

    # Check if normalization made any changes
    was_changed = normalized != channels

    return normalized, was_changed


def normalize_user_channels(users, config_file):
    """
    Normalize channels for all users and save if any changes were made

    Args:
        users: List of user configurations
        config_file: Path to config file

    Returns:
        Tuple of (updated_users, any_changes_made)
    """
    updated_users = []
    any_changes = False

    for user in users:
        user_copy = user.copy()
        original_channels = user_copy.get("channels", [])

        normalized_channels, was_changed = normalize_channels(original_channels)
        user_copy["channels"] = normalized_channels

        if was_changed:
            any_changes = True
            logger.log_event(
                "config",
                "channel_normalization_change",
                username=user_copy.get("username"),
                original_count=len(original_channels),
                new_count=len(normalized_channels),
                original=original_channels,
                new=normalized_channels,
            )

        updated_users.append(user_copy)

    # Save if any changes were made
    if any_changes:
        try:
            save_users_to_config(updated_users, config_file)
            logger.log_event(
                "config",
                "channel_normalization_saved",
                user_count=len(updated_users),
            )
        except Exception as e:
            logger.log_event(
                "config",
                "channel_normalization_save_failed",
                level=logging.ERROR,
                error=str(e),
                error_type=type(e).__name__,
            )

    return updated_users, any_changes


async def setup_missing_tokens(users, config_file):
    """
    Automatically setup tokens for users that don't have them or can't renew them.
    Returns updated users list with new tokens.
    """
    updated_users = []
    needs_config_save = False

    for user in users:
        user_result = await _setup_user_tokens(user)
        updated_users.append(user_result["user"])
        if user_result["tokens_updated"]:
            needs_config_save = True

    # Save config if any tokens were updated
    if needs_config_save:
        _save_updated_config(updated_users, config_file)

    return updated_users


async def _setup_user_tokens(user):
    """Setup tokens for a single user. Returns dict with user and update status."""
    username = user.get("username", "Unknown")
    client_id = user.get("client_id", "")
    client_secret = user.get("client_secret", "")

    # Check if user has basic credentials
    if not client_id or not client_secret:
        logger.log_event(
            "config",
            "token_setup_validation_failed",  # reuse existing token setup validation failed template
            level=logging.ERROR,
            username=username,
        )
        return {"user": user, "tokens_updated": False}

    # Check if tokens exist and are valid/renewable
    tokens_result = await _validate_or_refresh_tokens(user)
    if tokens_result["valid"]:
        return {
            "user": tokens_result["user"],
            "tokens_updated": tokens_result["updated"],
        }

    # Need new tokens via device flow
    return await _get_new_tokens_via_device_flow(user, client_id, client_secret)


async def _validate_or_refresh_tokens(user):
    """
    Validate existing tokens or refresh them using the standalone token validator.
    This avoids circular imports between config.py and bot.py.
    """
    try:
        return await token_validator.validate_user_tokens(user)
    except Exception:
        return {"valid": False, "user": user, "updated": False}


async def _get_new_tokens_via_device_flow(user, client_id, client_secret):
    """Get new tokens using device flow and ensure they're saved to config."""
    username = user.get("username", "Unknown")
    logger.log_event("config", "token_setup_start", username=username)

    device_flow = DeviceCodeFlow(client_id, client_secret)
    try:
        token_result = await device_flow.get_user_tokens(username)
        if token_result:
            new_access_token, new_refresh_token = token_result
            user["access_token"] = new_access_token
            user["refresh_token"] = new_refresh_token

            # Immediately validate the new tokens to ensure they work
            # and get expiry information for proactive refresh
            validation_result = await _validate_new_tokens(user)
            if validation_result["valid"]:
                logger.log_event("config", "token_setup_success", username=username)
                return {"user": validation_result["user"], "tokens_updated": True}
            logger.log_event(
                "config",
                "token_setup_validation_failed",
                level=logging.WARNING,
                username=username,
            )
            # Still save them, might work later
            return {"user": user, "tokens_updated": True}
        logger.log_event(
            "config", "token_setup_failed", level=logging.ERROR, username=username
        )
        return {"user": user, "tokens_updated": False}
    except Exception as e:
        logger.log_event(
            "config",
            "token_setup_exception",
            level=logging.ERROR,
            username=username,
            error=str(e),
            error_type=type(e).__name__,
        )
        return {"user": user, "tokens_updated": False}


async def _validate_new_tokens(user):
    """Validate newly obtained tokens."""
    try:
        return await token_validator.validate_new_tokens(user)
    except Exception:
        return {"valid": False, "user": user}


def _save_updated_config(updated_users, config_file):
    """Save updated configuration to file."""
    try:
        save_users_to_config(updated_users, config_file)
        logger.log_event("config", "tokens_update_saved", user_count=len(updated_users))
    except Exception as e:
        logger.log_event(
            "config",
            "tokens_update_save_failed",
            level=logging.ERROR,
            error=str(e),
            error_type=type(e).__name__,
        )
