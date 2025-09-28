"""Configuration validation utilities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model import UserConfig


class ConfigValidator:
    """Handles validation and filtering of user configurations."""

    @staticmethod
    def validate_and_filter_users(
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

    @staticmethod
    def validate_and_filter_users_to_dataclasses(
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
            if not uc.validate():  # Additional validation to filter users with empty channels or invalid usernames
                continue
            uname = uc.username.lower()
            if uname in seen:
                continue
            seen.add(uname)
            valid.append(uc)
        return valid
