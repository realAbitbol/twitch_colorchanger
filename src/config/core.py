"""Core configuration management utilities (moved from top-level config.py)."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable, Sequence
from typing import Any

import aiohttp

from .model import UserConfig  # normalize_user_list provided below
from .repository import ConfigRepository


def normalize_user_list(
    users: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Normalize a list of user configurations.

    Args:
        users: Iterable of user config dictionaries.

    Returns:
        Tuple of (normalized_users, changed_any) where changed_any is True
        if any user config was modified during normalization.
    """
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
    """Load user configurations from the config file.

    Args:
        config_file: Path to the configuration file.

    Returns:
        List of user config dictionaries.
    """
    repo = ConfigRepository(config_file)
    return repo.load_raw()


def save_users_to_config(users: Sequence[dict[str, Any]], config_file: str) -> None:
    """Save user configurations to the config file.

    Args:
        users: Sequence of user config dictionaries.
        config_file: Path to the configuration file.
    """
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
    """Update a user configuration in the config file.

    Args:
        user_config_dict: Dictionary containing user configuration data.
        config_file: Path to the configuration file.

    Returns:
        True if the update was successful, False otherwise.
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
    except (ValueError, RuntimeError, OSError) as e:
        _log_update_failed(e, user_config_dict)
        return False


def _merge_user(
    users: list[dict[str, Any]], uc: UserConfig
) -> tuple[list[dict[str, Any]], bool]:
    """Merge a user config into the list of users.

    Args:
        users: List of existing user configs.
        uc: UserConfig instance to merge.

    Returns:
        Tuple of (updated_users, replaced) where replaced is True if an
        existing user was replaced.
    """
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
    """Log an invalid user update and return False.

    Args:
        uc: UserConfig instance that failed validation.

    Returns:
        False to indicate failure.
    """
    logging.warning(
        f"🚫 Rejected invalid user update username={uc.username or 'Unknown'}"
    )
    return False


def _log_update_normalized(uc: UserConfig) -> None:
    """Log a normalized user update.

    Args:
        uc: UserConfig instance that was normalized.
    """
    logging.info(
        f"🛠️ User update normalized username={uc.username} channels={len(uc.channels)}"
    )


def _log_update_failed(e: Exception, user_config_dict: dict[str, Any]) -> None:
    """Log a failed user update.

    Args:
        e: The exception that occurred.
        user_config_dict: The user config dictionary that caused the failure.
    """
    username = (
        user_config_dict.get("username") if isinstance(user_config_dict, dict) else None
    )
    logging.error(
        f"💥 Failed to update user in config: {username} - {type(e).__name__}: {e}"
    )


def _validate_and_filter_users(
    raw_users: Iterable[dict[str, Any] | object],
) -> list[dict[str, Any]]:
    """Validate and filter raw user configurations.

    Args:
        raw_users: Iterable of raw user data.

    Returns:
        List of valid user config dictionaries.
    """
    from pydantic import ValidationError

    valid: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        try:
            uc = UserConfig.from_dict(item)
        except ValidationError:
            continue
        if not uc.validate():  # Additional validation to filter users with empty channels or invalid usernames
            continue
        uname = uc.username.lower()
        if uname in seen:
            continue
        seen.add(uname)
        valid.append(uc.to_dict())
    return valid


def _validate_and_filter_users_to_dataclasses(
    raw_users: Iterable[dict[str, Any] | object],
) -> list[UserConfig]:
    """Validate and filter raw user configurations to dataclasses.

    Args:
        raw_users: Iterable of raw user data.

    Returns:
        List of valid UserConfig instances.
    """
    from pydantic import ValidationError

    valid: list[UserConfig] = []
    seen: set[str] = set()
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        try:
            uc = UserConfig.from_dict(item)
        except ValidationError:
            continue
        uname = uc.username.lower()
        if uname in seen:
            continue
        seen.add(uname)
        valid.append(uc)
    return valid


def get_configuration() -> list[UserConfig]:
    """Load and validate user configurations from the config file.

    Returns:
        List of valid UserConfig instances.

    Raises:
        SystemExit: If no config file or no valid users found.
    """
    config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
    users = load_users_from_config(config_file)
    if not users:
        logging.error("📁 No configuration file found")
        logging.error("📄 Instruction emitted for creating config file")
        sys.exit(1)
    valid_users = _validate_and_filter_users_to_dataclasses(users)
    if not valid_users:
        logging.error("⚠️ No valid user configurations found")
        sys.exit(1)
    logging.info(f"✅ Valid user configurations found count={len(valid_users)}")
    return valid_users


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
    """
    import aiohttp

    from ..api.twitch import TwitchAPI
    from ..auth_token.provisioner import TokenProvisioner  # local import

    required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    updated_users: list[UserConfig] = []
    any_updates = False

    async with aiohttp.ClientSession() as session:
        provisioner = TokenProvisioner(session)
        api = TwitchAPI(session)
        for user in users:
            changed, processed_user = await _process_single_user_tokens_dataclass(
                user, api, provisioner, required_scopes
            )
            if changed:
                any_updates = True
            updated_users.append(processed_user)
    if any_updates:
        _save_updated_config_dataclass(updated_users, config_file)
    return updated_users


def _extract_token_triplet(user: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Extract token triplet from user config.

    Args:
        user: User config dictionary.

    Returns:
        Tuple of (access_token, refresh_token, token_expiry).
    """
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
    """Return True if existing tokens are valid & retained else False (forcing provisioning).

    Args:
        user: User config dictionary.
        access: Access token.
        refresh: Refresh token.
        api: TwitchAPI instance.
        required_scopes: Set of required scopes.

    Returns:
        True if tokens are valid and retained.
    """
    if not (access and refresh):
        return False
    try:
        validation = await api.validate_token(access)
        # If validation failed (None or non-dict) retain existing tokens; treat as transient.
        if not isinstance(validation, dict):
            return True
        raw_scopes = validation.get("scopes")
        # If scopes key missing or not a list, retain tokens (don't nuke on malformed payload)
        if not isinstance(raw_scopes, list):
            return True
        scopes_list = [str(s).lower() for s in raw_scopes]
        scope_set = set(scopes_list)
        missing = _missing_scopes(required_scopes, scope_set)
        if not missing:
            return True
        # Double-check via one revalidation to avoid false positives.
        confirmed_missing, confirmed_set = await _confirm_missing_scopes(
            api, access, required_scopes
        )
        if not confirmed_missing:
            return True
        _invalidate_for_missing_scopes(
            user,
            required_scopes,
            confirmed_set if confirmed_set is not None else scope_set,
        )
        return False
    except (aiohttp.ClientError, ValueError, RuntimeError):
        # Leave tokens untouched if validation fails; treat as retained
        return True


async def _validate_or_invalidate_scopes_dataclass(
    user: UserConfig,
    access: Any,
    refresh: Any,
    api: Any,
    required_scopes: set[str],
) -> bool:
    """Return True if existing tokens are valid & retained else False (forcing provisioning) for dataclass.

    Args:
        user: UserConfig instance.
        access: Access token.
        refresh: Refresh token.
        api: TwitchAPI instance.
        required_scopes: Set of required scopes.

    Returns:
        True if tokens are valid and retained.
    """
    if not (access and refresh):
        return False
    try:
        validation = await api.validate_token(access)
        # If validation failed (None or non-dict) retain existing tokens; treat as transient.
        if not isinstance(validation, dict):
            return True
        raw_scopes = validation.get("scopes")
        # If scopes key missing or not a list, retain tokens (don't nuke on malformed payload)
        if not isinstance(raw_scopes, list):
            return True
        scopes_list = [str(s).lower() for s in raw_scopes]
        scope_set = set(scopes_list)
        missing = _missing_scopes(required_scopes, scope_set)
        if not missing:
            return True
        # Double-check via one revalidation to avoid false positives.
        confirmed_missing, confirmed_set = await _confirm_missing_scopes(
            api, access, required_scopes
        )
        if not confirmed_missing:
            return True
        _invalidate_for_missing_scopes_dataclass(
            user,
            required_scopes,
            confirmed_set if confirmed_set is not None else scope_set,
        )
        return False
    except (aiohttp.ClientError, ValueError, RuntimeError):
        # Leave tokens untouched if validation fails; treat as retained
        return True


def _missing_scopes(required: set[str], current: set[str]) -> list[str]:
    """Get list of missing scopes.

    Args:
        required: Set of required scopes.
        current: Set of current scopes.

    Returns:
        Sorted list of missing scopes.
    """
    return sorted(s for s in required if s not in current)


async def _confirm_missing_scopes(
    api: Any,
    access: str,
    required: set[str],
) -> tuple[list[str], set[str] | None]:
    """Confirm missing scopes via revalidation.

    Args:
        api: TwitchAPI instance.
        access: Access token.
        required: Set of required scopes.

    Returns:
        Tuple of (missing_scopes, confirmed_set).
    """
    try:
        second = await api.validate_token(access)
    except (aiohttp.ClientError, ValueError, RuntimeError):
        return [], None  # Treat failure as retain (no confirmed missing)
    if not isinstance(second, dict) or not isinstance(second.get("scopes"), list):
        return [], None
    second_set = {str(s).lower() for s in second["scopes"]}
    second_missing = _missing_scopes(required, second_set)
    if second_missing:
        return second_missing, second_set
    return [], second_set


def _invalidate_for_missing_scopes(
    user: dict[str, Any], required_scopes: set[str], current_set: set[str]
) -> None:
    """Invalidate tokens for missing scopes.

    Args:
        user: User config dictionary.
        required_scopes: Set of required scopes.
        current_set: Set of current scopes.
    """
    user.pop("access_token", None)
    user.pop("refresh_token", None)
    user.pop("token_expiry", None)
    logging.warning(
        f"🚫 Token scopes missing required={';'.join(sorted(required_scopes))} got={';'.join(sorted(current_set)) if current_set else '<none>'} user={user.get('username')} invalidated=true"
    )


def _invalidate_for_missing_scopes_dataclass(
    user: UserConfig, required_scopes: set[str], current_set: set[str]
) -> None:
    """Invalidate tokens for missing scopes for dataclass.

    Args:
        user: UserConfig instance.
        required_scopes: Set of required scopes.
        current_set: Set of current scopes.
    """
    user.access_token = None
    user.refresh_token = None
    # token_expiry not in UserConfig
    logging.warning(
        f"🚫 Token scopes missing required={';'.join(sorted(required_scopes))} got={';'.join(sorted(current_set)) if current_set else '<none>'} user={user.username} invalidated=true"
    )


async def _process_single_user_tokens_dataclass(
    user: UserConfig,
    api: Any,
    provisioner: Any,
    required_scopes: set[str],
) -> tuple[bool, UserConfig]:
    """Process a single user's tokens for dataclass.

    Args:
        user: UserConfig instance.
        api: TwitchAPI instance.
        provisioner: TokenProvisioner instance.
        required_scopes: Set of required scopes.

    Returns:
        Tuple of (changed_flag, user_dataclass) where changed_flag is True
        when token fields were updated.
    """
    access, refresh, _ = user.access_token, user.refresh_token, None
    tokens_valid = await _validate_or_invalidate_scopes_dataclass(
        user, access, refresh, api, required_scopes
    )
    if tokens_valid:
        return False, user
    client_id_v = user.client_id or ""
    client_secret_v = user.client_secret or ""
    new_access, new_refresh, _ = await provisioner.provision(
        user.username,
        client_id_v,
        client_secret_v,
        None,
        None,
        None,
    )
    if new_access and new_refresh:
        user.access_token = new_access
        user.refresh_token = new_refresh
        # Note: token_expiry not in UserConfig, so ignore
        return True, user
    return False, user


def _save_updated_config_dataclass(
    updated_users: Sequence[UserConfig], config_file: str
) -> None:
    """Save updated user configurations for dataclasses.

    Args:
        updated_users: Sequence of updated UserConfig instances.
        config_file: Path to the configuration file.
    """
    try:
        user_dicts = [uc.to_dict() for uc in updated_users]
        save_users_to_config(user_dicts, config_file)
        logging.info("💾 Tokens update saved")
    except (OSError, ValueError, RuntimeError) as e:
        logging.error(f"💥 Tokens update save failed: {type(e).__name__}")
