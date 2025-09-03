"""
Configuration management for the Twitch Color Changer bot
"""

import logging
import os
import sys
import time

from .config_repository import ConfigRepository
from .constants import CONFIG_WRITE_DEBOUNCE
from .logger import logger
from .user_config_model import UserConfig, normalize_user_list


def load_users_from_config(config_file):
    repo = ConfigRepository(config_file)
    return repo.load_raw()


########################
# Removed legacy helpers (#setup, #ownership, #permissions, #log_* verification).
# Functionality replaced by ConfigRepository & structured events elsewhere.
########################


def save_users_to_config(users, config_file):
    # Normalize channel lists & usernames
    normalized_users, changed = normalize_user_list(users)
    repo = ConfigRepository(config_file)
    wrote = repo.save_users(normalized_users)
    if wrote:
        repo.verify_readback()
    else:
        if changed:
            # Normalization changed data but checksum prevented write - force write
            # because original order differences may have produced same checksum
            repo._last_checksum = None  # reset checksum
            repo.save_users(normalized_users)
            repo.verify_readback()
    time.sleep(CONFIG_WRITE_DEBOUNCE)


def update_user_in_config(user_config_dict, config_file):
    """Update or insert a user's configuration using the UserConfig model.

    1. Build UserConfig from incoming dict
    2. Normalize (username + channels)
    3. Basic validate (structure only)
    4. Merge with existing if present, else append
    5. Persist via repository (with checksum skip)
    """
    try:
        uc = UserConfig.from_dict(user_config_dict)
        changed = uc.normalize()
        if not uc.validate():
            return _log_update_invalid(uc)

        users = load_users_from_config(config_file)
        users, replaced = _merge_user(users, uc)

        if not replaced:
            users.append(uc.to_dict())

        save_users_to_config(users, config_file)
        if changed:
            _log_update_normalized(uc)
        return True
    except Exception as e:  # noqa: BLE001
        _log_update_failed(e, user_config_dict)
        return False


def _merge_user(users, uc: UserConfig):  # Helper to merge existing user
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


def _log_update_invalid(uc: UserConfig):
    logger.log_event(
        "config",
        "update_user_invalid",
        level=logging.WARNING,
        username=uc.username or "Unknown",
    )
    return False


def _log_update_normalized(uc: UserConfig):
    logger.log_event(
        "config",
        "update_user_normalized",
        username=uc.username,
        channel_count=len(uc.channels),
    )


def _log_update_failed(e: Exception, user_config_dict):
    logger.log_event(
        "config",
        "update_user_failed",
        level=logging.ERROR,
        error=str(e),
        error_type=type(e).__name__,
        username=user_config_dict.get("username")
        if isinstance(user_config_dict, dict)
        else None,
    )


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


def _validate_and_filter_users(raw_users):
    """Return list of valid user dicts from raw list."""
    placeholders = {
        "test",
        "placeholder",
        "your_token_here",
        "fake_token",
        "example_token_twenty_chars",
    }

    def auth_ok(u: UserConfig) -> bool:
        access = u.access_token or ""
        token_valid = (
            access and len(access) >= 20 and access.lower() not in placeholders
        )
        client_valid = (
            (u.client_id and u.client_secret)
            and len(u.client_id) >= 10  # type: ignore[arg-type]
            and len(u.client_secret) >= 10  # type: ignore[arg-type]
        )
        return bool(token_valid or client_valid)

    def channels_ok(u: UserConfig) -> bool:
        chs = u.channels
        if not chs or not isinstance(chs, list):
            return False
        return all(isinstance(c, str) and len(c.strip()) >= 3 for c in chs)

    valid: list[dict] = []
    seen: set[str] = set()
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        uc = UserConfig.from_dict(item)
        uname = uc.username.lower()
        if (
            not (3 <= len(uname) <= 25)
            or not auth_ok(uc)
            or not channels_ok(uc)
            or uname in seen
        ):
            continue
        seen.add(uname)
        valid.append(uc.to_dict())
    return valid


def get_configuration():
    """Get configuration from config file only"""
    config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
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
    valid_users = _validate_and_filter_users(users)
    if not valid_users:
        logger.log_event(
            "config", "no_valid_users", level=logging.ERROR, config_file=config_file
        )
        sys.exit(1)
    logger.log_event("config", "valid_users_found", user_count=len(valid_users))
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


########################
# Legacy normalize_channels removed; use UserConfig normalization instead.
########################


def normalize_user_channels(users, config_file):
    normalized_users, any_changes = normalize_user_list(users)
    if any_changes:
        try:
            save_users_to_config(normalized_users, config_file)
            logger.log_event(
                "config",
                "channel_normalization_saved",
                user_count=len(normalized_users),
            )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "config",
                "channel_normalization_save_failed",
                level=logging.ERROR,
                error=str(e),
                error_type=type(e).__name__,
            )
    return normalized_users, any_changes


async def setup_missing_tokens(users, config_file, dry_run: bool = False):
    """Provision tokens for users needing refresh or creation using TokenProvisioner.

    dry_run: if True, only logs decisions; no mutation or file writes.
    """
    from .token_provisioner import TokenProvisioner  # local import to avoid cycles

    provisioner = TokenProvisioner(dry_run=dry_run)
    updated_users: list[dict] = []
    any_updates = False
    for user in users:
        result = await provisioner.provision(user)
        updated_users.append(result.user)
        if result.updated:
            any_updates = True
    if any_updates and not dry_run:
        _save_updated_config(updated_users, config_file)
    return updated_users


## Legacy token validation/refresh helpers removed (now handled by TokenProvisioner).


## Legacy _get_new_tokens_via_device_flow removed (provision now centralized).  # noqa: ERA001


## Legacy _validate_new_tokens removed (handled inside TokenProvisioner or token_client).  # noqa: ERA001


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
