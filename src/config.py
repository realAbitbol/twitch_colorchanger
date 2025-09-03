"""
Configuration management for the Twitch Color Changer bot
"""

import logging
import os
import sys
import time
from datetime import datetime

import aiohttp

from .config_repository import ConfigRepository
from .constants import CONFIG_WRITE_DEBOUNCE
from .device_flow import DeviceCodeFlow
from .logger import logger
from .token_client import TokenClient, TokenOutcome
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
    """Validate or refresh tokens via TokenClient with minimal branching."""
    username = user.get("username", "Unknown")

    access_token = user.get("access_token")
    client_id = user.get("client_id")
    client_secret = user.get("client_secret")
    refresh_token = user.get("refresh_token")

    if not access_token:
        return _token_validation_fail(user, username, "validation_missing_access_token")
    if not client_id or not client_secret:
        return _token_validation_fail(
            user,
            username,
            "validation_missing_client_credentials",
            has_client_id=bool(client_id),
            has_client_secret=bool(client_secret),
        )

    try:
        async with aiohttp.ClientSession() as session:
            client = TokenClient(str(client_id), str(client_secret), session)
            outcome_obj = await client.ensure_fresh(
                username,
                str(access_token),
                str(refresh_token) if refresh_token else None,
                None,
                force_refresh=False,
            )
        return _handle_token_client_outcome(user, username, outcome_obj)
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "token",
            "validation_error",
            level=logging.ERROR,
            user=username,
            error=str(e),
            error_type=type(e).__name__,
        )
        return {"valid": False, "user": user, "updated": False}


def _handle_token_client_outcome(
    user: dict, username: str, outcome_obj
):  # Helper extracted
    if outcome_obj.outcome == TokenOutcome.VALID:
        if outcome_obj.expiry:
            remaining = int((outcome_obj.expiry - datetime.now()).total_seconds())
            hours, minutes = divmod(max(remaining, 0) // 60, 60)
            duration_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
            logger.log_event(
                "token",
                "validation_valid",
                user=username,
                expires_in_seconds=remaining,
                human_remaining=duration_str,
            )
        return {"valid": True, "user": user, "updated": False}
    if outcome_obj.outcome == TokenOutcome.REFRESHED:
        if outcome_obj.access_token:
            user["access_token"] = outcome_obj.access_token
        if outcome_obj.refresh_token:
            user["refresh_token"] = outcome_obj.refresh_token
        logger.log_event("token", "validation_refreshed", user=username)
        return {"valid": True, "user": user, "updated": True}
    logger.log_event("token", "validation_failed", level=logging.ERROR, user=username)
    return {"valid": False, "user": user, "updated": False}


def _token_validation_fail(user: dict, username: str, event: str, **extra):
    """Log a validation failure event and return a standard failure structure."""
    logger.log_event("token", event, level=logging.WARNING, user=username, **extra)
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
    """Validate newly obtained tokens via TokenClient."""
    username = user.get("username", "Unknown")
    required_keys = ["client_id", "client_secret", "access_token", "refresh_token"]
    for key in required_keys:
        if key not in user:
            logger.log_event(
                "token",
                "new_token_validation_missing_field",
                level=logging.ERROR,
                user=username,
                field=key,
            )
            return {"valid": False, "user": user}
    try:
        async with aiohttp.ClientSession() as session:
            client = TokenClient(
                str(user["client_id"]),
                str(user["client_secret"]),
                session,
            )
            result = await client.validate(username, str(user["access_token"]))
        if result.outcome == TokenOutcome.VALID:
            logger.log_event("token", "new_validation_success", user=username)
            return {"valid": True, "user": user}
        logger.log_event(
            "token", "new_validation_failed", level=logging.WARNING, user=username
        )
        return {"valid": False, "user": user}
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "token",
            "new_validation_exception",
            level=logging.ERROR,
            user=username,
            error=str(e),
            error_type=type(e).__name__,
        )
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
