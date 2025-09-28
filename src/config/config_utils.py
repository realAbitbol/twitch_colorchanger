"""Configuration utility functions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .model import UserConfig


def normalize_user_list(
    users: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Normalize a list of user configurations.

    Args:
        users: Sequence of user config dictionaries.

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
