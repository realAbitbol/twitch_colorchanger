"""Core configuration management utilities (moved from top-level config.py)."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable, Sequence
from typing import Any

from ..logs.logger import logger
from .model import UserConfig  # normalize_user_list provided below
from .repository import ConfigRepository


def normalize_user_list(
    users: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:  # minimal shim if original lived elsewhere
    # If model exposed normalize_user_list previously, replicate behavior:
    normalized = []
    changed_any = False
    for item in users:
        if isinstance(item, dict):
            uc = UserConfig.from_dict(item)
            if uc.normalize():
                changed_any = True
            normalized.append(uc.to_dict())
    return normalized, changed_any


def load_users_from_config(config_file: str) -> list[dict[str, Any]]:
    repo = ConfigRepository(config_file)
    return repo.load_raw()


def save_users_to_config(users: Sequence[dict[str, Any]], config_file: str) -> None:
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


def update_user_in_config(user_config_dict: dict[str, Any], config_file: str) -> bool:
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


def _merge_user(
    users: list[dict[str, Any]], uc: UserConfig
) -> tuple[list[dict[str, Any]], bool]:
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


def _log_update_invalid(uc: UserConfig) -> bool:
    logger.log_event(
        "config",
        "update_user_invalid",
        level=logging.WARNING,
        username=uc.username or "Unknown",
    )
    return False


def _log_update_normalized(uc: UserConfig) -> None:
    logger.log_event(
        "config",
        "update_user_normalized",
        username=uc.username,
        channel_count=len(uc.channels),
    )


def _log_update_failed(e: Exception, user_config_dict: dict[str, Any]) -> None:
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


def _user_auth_valid(u: UserConfig, placeholders: set[str]) -> bool:
    """Return True if token or (client_id+client_secret) looks usable."""
    access = u.access_token or ""
    token_valid = bool(
        access and len(access) >= 20 and access.lower() not in placeholders
    )
    cid = u.client_id or ""
    csec = u.client_secret or ""
    client_valid = bool(cid and csec and len(cid) >= 10 and len(csec) >= 10)
    return token_valid or client_valid


def _user_channels_valid(u: UserConfig) -> bool:
    chs = u.channels
    if not chs or not isinstance(chs, list):
        return False
    return all(isinstance(c, str) and len(c.strip()) >= 3 for c in chs)


def _user_username_valid(name: str) -> bool:
    return 3 <= len(name) <= 25


def _is_valid_user(uc: UserConfig, seen: set[str], placeholders: set[str]) -> bool:
    uname = uc.username.lower()
    if not _user_username_valid(uname):
        return False
    if uname in seen:
        return False
    if not _user_auth_valid(uc, placeholders):
        return False
    if not _user_channels_valid(uc):
        return False
    return True


def _validate_and_filter_users(
    raw_users: Iterable[dict[str, Any] | object],
) -> list[dict[str, Any]]:
    placeholders = {
        "test",
        "placeholder",
        "your_token_here",
        "fake_token",
        "example_token_twenty_chars",
    }
    valid: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        uc = UserConfig.from_dict(item)
        if not _is_valid_user(uc, seen, placeholders):
            continue
        seen.add(uc.username.lower())
        valid.append(uc.to_dict())
    return valid


def get_configuration() -> list[dict[str, Any]]:
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


def print_config_summary(users: Sequence[dict[str, Any]]) -> None:
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


def normalize_user_channels(
    users: Sequence[dict[str, Any]], config_file: str
) -> tuple[list[dict[str, Any]], bool]:
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


async def setup_missing_tokens(
    users: list[dict[str, Any]], config_file: str
) -> list[dict[str, Any]]:
    import aiohttp

    from ..api.twitch import TwitchAPI
    from ..token.provisioner import TokenProvisioner  # local import

    required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    updated_users: list[dict[str, Any]] = []
    any_updates = False

    async with aiohttp.ClientSession() as session:
        provisioner = TokenProvisioner(session)
        api = TwitchAPI(session)
        for user in users:
            changed, processed_user = await _process_single_user_tokens(
                user, api, provisioner, required_scopes
            )
            if changed:
                any_updates = True
            updated_users.append(processed_user)
    if any_updates:
        _save_updated_config(updated_users, config_file)
    return updated_users


def _extract_token_triplet(user: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        user.get("access_token"),
        user.get("refresh_token"),
        user.get("token_expiry"),
    )


async def _validate_or_invalidate_scopes(
    user: dict[str, Any],
    access: Any,
    refresh: Any,
    api: Any,
    required_scopes: set[str],
) -> bool:
    """Return True if existing tokens are valid & retained else False (forcing provisioning)."""
    if not (access and refresh):
        return False
    try:
        validation = await api.validate_token(access)
        raw_scopes = validation.get("scopes") if isinstance(validation, dict) else None
        scopes_list: list[str] = (
            [str(s).lower() for s in raw_scopes] if isinstance(raw_scopes, list) else []
        )
        scope_set = set(scopes_list)
        missing = sorted(s for s in required_scopes if s not in scope_set)
        if missing:
            # Invalidate tokens to trigger device flow re-provision
            user.pop("access_token", None)
            user.pop("refresh_token", None)
            user.pop("token_expiry", None)
            from ..logs.logger import logger as _logger  # local import

            _logger.log_event(
                "token",
                "scopes_missing_invalidate",
                user=user.get("username"),
                # Provide fields expected by template: required, current.
                required=";".join(sorted(required_scopes)),
                current=";".join(sorted(scope_set)) if scope_set else "<none>",
            )
            return False
        return True
    except Exception:  # noqa: BLE001
        # Leave tokens untouched if validation fails; treat as retained
        return True


async def _process_single_user_tokens(
    user: dict[str, Any],
    api: Any,
    provisioner: Any,
    required_scopes: set[str],
) -> tuple[bool, dict[str, Any]]:
    """Process a single user's tokens.

    Returns (changed_flag, user_dict).
    changed_flag True when we updated (provisioned or re-provisioned) token fields.
    """
    access, refresh, _ = _extract_token_triplet(user)
    tokens_valid = await _validate_or_invalidate_scopes(
        user, access, refresh, api, required_scopes
    )
    if tokens_valid:
        return False, user
    client_id_v = user.get("client_id") or ""
    client_secret_v = user.get("client_secret") or ""
    new_access, new_refresh, new_expiry = await provisioner.provision(
        user.get("username", "unknown"),
        client_id_v,
        client_secret_v,
        None,
        None,
        None,
    )
    if new_access and new_refresh:
        user["access_token"] = new_access
        user["refresh_token"] = new_refresh
        if new_expiry:
            user["token_expiry"] = new_expiry
        return True, user
    return False, user


def _save_updated_config(
    updated_users: Sequence[dict[str, Any]], config_file: str
) -> None:
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
