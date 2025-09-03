"""Core configuration management utilities (moved from top-level config.py)."""

from __future__ import annotations

import logging
import os
import sys

from project_logging.logger import logger

from .model import UserConfig  # normalize_user_list provided below
from .repository import ConfigRepository


def normalize_user_list(users):  # minimal shim if original lived elsewhere
    # If model exposed normalize_user_list previously, replicate behavior:
    normalized = []
    changed_any = False
    for item in users:
        if not isinstance(item, dict):
            continue
        uc = UserConfig.from_dict(item)
        if uc.normalize():
            changed_any = True
        normalized.append(uc.to_dict())
    return normalized, changed_any


def load_users_from_config(config_file):
    repo = ConfigRepository(config_file)
    return repo.load_raw()


def save_users_to_config(users, config_file):
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


def update_user_in_config(user_config_dict, config_file):
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


def _merge_user(users, uc: UserConfig):
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


def _validate_and_filter_users(raw_users):
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
    import aiohttp

    from auth_token.provisioner import TokenProvisioner  # local import

    updated_users: list[dict] = []
    any_updates = False
    async with aiohttp.ClientSession() as session:
        provisioner = TokenProvisioner(session)
        for user in users:
            access = user.get("access_token")
            refresh = user.get("refresh_token")
            expiry = user.get("token_expiry")
            if access and refresh:
                updated_users.append(user)
                continue
            result_access, result_refresh, result_expiry = await provisioner.provision(
                user.get("username", "unknown"),
                user.get("client_id"),
                user.get("client_secret"),
                access,
                refresh,
                expiry,
            )
            if result_access and result_refresh:
                user["access_token"] = result_access
                user["refresh_token"] = result_refresh
                if result_expiry:
                    user["token_expiry"] = result_expiry
                any_updates = True
            updated_users.append(user)
    if any_updates:
        _save_updated_config(updated_users, config_file)
    return updated_users


def _save_updated_config(updated_users, config_file):
    try:
        save_users_to_config(updated_users, config_file)
        logger.log_event("config", "tokens_update_saved", user_count=len(updated_users))
    except Exception as e:  # noqa: BLE001
        logger.log_event(
            "config",
            "tokens_update_save_failed",
            level=logging.ERROR,
            error=str(e),
            error_type=type(e).__name__,
        )
