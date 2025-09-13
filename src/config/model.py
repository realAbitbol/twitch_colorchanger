from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast


def _normalize_channels(channels: list[str] | Any) -> tuple[list[str], bool]:
    """Normalize a list of channel names.

    Args:
        channels: List of channel names or any other type.

    Returns:
        Tuple of (normalized_channels, changed) where changed is True
        if the list was modified.
    """
    if not isinstance(channels, list):
        return [], True
    normalized = sorted(
        dict.fromkeys(
            ch.lower().strip().lstrip("#") for ch in channels if ch and ch.strip()
        )
    )
    changed = normalized != channels
    return normalized, changed


@dataclass
class UserConfig:
    """Represents a user's configuration for Twitch color changing.

    Attributes:
        username: The user's Twitch username.
        client_id: Twitch application client ID.
        client_secret: Twitch application client secret.
        access_token: OAuth access token.
        refresh_token: OAuth refresh token.
        channels: List of Twitch channels to monitor.
        is_prime_or_turbo: Whether user has Prime or Turbo subscription.
        enabled: Whether automatic color change is enabled.
    """

    username: str
    client_id: str | None = None
    client_secret: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    channels: list[str] = field(default_factory=list)
    is_prime_or_turbo: bool = True
    enabled: bool = True  # New flag to enable/disable automatic color change

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UserConfig:
        """Create UserConfig from a dictionary.

        Args:
            data: Dictionary containing user configuration data.

        Returns:
            UserConfig instance.
        """
        channels_raw = data.get("channels")
        channels: list[str]
        if isinstance(channels_raw, list):
            channels = [str(c).strip() for c in channels_raw if isinstance(c, str)]
        else:
            channels = []
        return cls(
            username=str(data.get("username", "")).strip(),
            client_id=cast(str | None, data.get("client_id")),
            client_secret=cast(str | None, data.get("client_secret")),
            access_token=cast(str | None, data.get("access_token")),
            refresh_token=cast(str | None, data.get("refresh_token")),
            channels=channels,
            is_prime_or_turbo=bool(data.get("is_prime_or_turbo", True)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert UserConfig to a dictionary.

        Returns:
            Dictionary representation of the UserConfig.
        """
        data: dict[str, Any] = {
            "username": self.username,
            "channels": self.channels,
            "is_prime_or_turbo": self.is_prime_or_turbo,
            "enabled": self.enabled,
        }
        if self.client_id:
            data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if self.access_token:
            data["access_token"] = self.access_token
        if self.refresh_token:
            data["refresh_token"] = self.refresh_token
        return data

    def normalize(self) -> bool:
        """Normalize the UserConfig fields.

        Returns:
            True if any fields were changed during normalization.
        """
        changed = False
        # Normalize username
        norm_username = self.username.strip()
        if norm_username != self.username:
            self.username = norm_username
            changed = True
        # Normalize channels
        normalized, channel_changed = _normalize_channels(self.channels)
        if channel_changed:
            logging.info(
                f"🛠️ Channel normalization change {self.channels}->{normalized}"
            )
            self.channels = normalized
            changed = True
        return changed

    def validate_basic(self) -> bool:
        """Perform basic validation on the UserConfig.

        Returns:
            True if basic validation passes.
        """
        if not self.username or len(self.username) < 3:
            return False
        # Channels optional at this stage for partial configs
        return True

    # Public alias improving semantic clarity for external callers
    def validate(self) -> bool:
        """Return True if basic structural fields are acceptable.

        Returns:
            True if validation passes.
        """
        return self.validate_basic()

    # Removed ensure_prime_flag (unused).  # noqa: ERA001


def normalize_user_list(
    users: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Normalize a list of user configurations.

    Args:
        users: List of user config dictionaries.

    Returns:
        Tuple of (normalized_users, any_changes) where any_changes is True
        if any user was modified.
    """
    normalized_list: list[dict[str, Any]] = []
    any_changes = False
    for u in users:
        uc = UserConfig.from_dict(u)
        if uc.normalize():
            any_changes = True
        normalized_list.append(uc.to_dict())
    return normalized_list, any_changes


def normalize_channels_list(channels: list[str] | Any) -> tuple[list[str], bool]:
    """Public helper to normalize a channel list (used outside config paths).

    Args:
        channels: List of channel names or any other type.

    Returns:
        Tuple of (normalized_channels, changed).
    """
    return _normalize_channels(channels)
