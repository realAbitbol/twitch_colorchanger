"""Token setup and provisioning coordination utilities."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import aiohttp

from ..api.twitch import TwitchAPI
from ..auth_token.provisioner import TokenProvisioner
from .config_saver import ConfigSaver
from .model import UserConfig


class TokenSetupCoordinator:
    """Coordinates token provisioning and scope validation."""

    def __init__(self, saver: ConfigSaver | None = None) -> None:
        """Initialize TokenSetupCoordinator.

        Args:
            saver: ConfigSaver instance for saving configurations.
        """
        self.saver = saver or ConfigSaver()

    async def setup_missing_tokens(
        self,
        users: list[UserConfig], config_file: str
    ) -> list[UserConfig]:
        """Set up missing tokens for users.

        Args:
            users: List of UserConfig instances.
            config_file: Path to the configuration file.

        Returns:
            List of updated UserConfig instances.

        Raises:
            aiohttp.ClientError: If network requests fail.
            ValueError: If token provisioning fails.
            RuntimeError: If token setup process fails.
        """
        required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}
        updated_users: list[UserConfig] = []
        any_updates = False

        async with aiohttp.ClientSession() as session:
            provisioner = TokenProvisioner(session)
            api = TwitchAPI(session)
            for user in users:
                changed, processed_user = await self._process_single_user_tokens_dataclass(
                    user, api, provisioner, required_scopes
                )
                if changed:
                    any_updates = True
                updated_users.append(processed_user)
        if any_updates:
            self._save_updated_config_dataclass(updated_users, config_file)
        return updated_users

    async def _validate_or_invalidate_scopes(
        self,
        user: Any,
        access: Any,
        refresh: Any,
        api: Any,
        required_scopes: set[str],
    ) -> bool:
        """Return True if existing tokens are valid & retained else False (forcing provisioning).

        Args:
            user: User config (dict or UserConfig).
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
            missing = self._missing_scopes(required_scopes, scope_set)
            if not missing:
                return True
            # Double-check via one revalidation to avoid false positives.
            confirmed_missing, confirmed_set = await self._confirm_missing_scopes(
                api, access, required_scopes
            )
            if not confirmed_missing:
                return True
            self._invalidate_for_missing_scopes(
                user,
                required_scopes,
                confirmed_set if confirmed_set is not None else scope_set,
            )
            return False
        except (aiohttp.ClientError, ValueError, RuntimeError):
            # Leave tokens untouched if validation fails; treat as retained
            return True

    def _missing_scopes(self, required: set[str], current: set[str]) -> list[str]:
        """Get list of missing scopes.

        Args:
            required: Set of required scopes.
            current: Set of current scopes.

        Returns:
            Sorted list of missing scopes.
        """
        return sorted(s for s in required if s not in current)

    async def _confirm_missing_scopes(
        self,
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
        second_missing = self._missing_scopes(required, second_set)
        if second_missing:
            return second_missing, second_set
        return [], second_set

    def _invalidate_for_missing_scopes(
        self, user: Any, required_scopes: set[str], current_set: set[str]
    ) -> None:
        """Invalidate tokens for missing scopes.

        Args:
            user: User config (dict or UserConfig).
            required_scopes: Set of required scopes.
            current_set: Set of current scopes.
        """
        if isinstance(user, dict):
            user.pop("access_token", None)
            user.pop("refresh_token", None)
            user.pop("token_expiry", None)
            username = user.get("username")
        else:  # UserConfig
            user.access_token = None
            user.refresh_token = None
            # token_expiry not in UserConfig
            username = user.username
        logging.warning(
            f"🚫 Token scopes missing required={';'.join(sorted(required_scopes))} got={';'.join(sorted(current_set)) if current_set else '<none>'} user={username} invalidated=true"
        )

    async def _process_single_user_tokens_dataclass(
        self,
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
        tokens_valid = await self._validate_or_invalidate_scopes(
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
        self, updated_users: Sequence[UserConfig], config_file: str
    ) -> None:
        """Save updated user configurations for dataclasses.

        Args:
            updated_users: Sequence of updated UserConfig instances.
            config_file: Path to the configuration file.
        """
        try:
            user_dicts = [uc.to_dict() for uc in updated_users]
            self.saver.save_users_to_config(user_dicts, config_file)
            logging.info("💾 Tokens update saved")
        except (OSError, ValueError, RuntimeError) as e:
            logging.error(f"💥 Tokens update save failed: {type(e).__name__}")
