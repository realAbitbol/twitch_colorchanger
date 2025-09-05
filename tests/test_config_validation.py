import json
from typing import Any

import pytest

from src.config.core import _validate_and_filter_users, normalize_user_channels
from src.config.model import UserConfig


@pytest.fixture()
def sample_users() -> list[dict[str, Any]]:
    return [
        {"username": "Alice", "channels": ["Alice", "#ALICE"], "access_token": "x" * 25},
        {"username": "bob", "channels": ["bob", "bob"], "access_token": "y" * 25},
        {"username": "Bob", "channels": ["Bob"], "access_token": "z" * 25},  # duplicate (case-insensitive)
        {"username": "xy", "channels": ["xy"], "access_token": "t" * 25},  # too short username
        {"username": "carol", "channels": ["  ", "carol"], "access_token": "t" * 5},  # invalid token length
        {"username": "dave", "channels": [], "access_token": "a" * 30},  # no channels
        {"username": "eve", "channels": ["evE", "EVE", "eve"], "access_token": "b" * 30},
    ]


def test_validate_and_filter_users(sample_users):
    valid = _validate_and_filter_users(sample_users)
    # Expect: Alice (normalized), bob (first occurrence only), eve (dedup channels)
    usernames = {u["username"].lower() for u in valid}
    assert usernames == {"alice", "bob", "eve"}
    # Channel normalization happens via normalize_user_channels, not in raw filter
    alice = next(u for u in valid if u["username"].lower() == "alice")
    assert {c.lower().lstrip('#') for c in alice["channels"]} == {"alice"}
    eve = next(u for u in valid if u["username"].lower() == "eve")
    assert {c.lower().lstrip('#') for c in eve["channels"]} == {"eve"}


def test_normalize_user_channels_persists(tmp_path):
    # Write config file with messy channels to ensure save path triggers logging side path
    cfg = tmp_path / "twitch_colorchanger.conf"
    users = [
        {
            "username": "Frank",
            "channels": ["Frank", " frank", "#FRANK"],
            "access_token": "q" * 30,
        }
    ]
    cfg.write_text(json.dumps(users))
    normalized, changed = normalize_user_channels(users, str(cfg))
    assert changed is True
    assert normalized[0]["channels"] == ["frank"]


def test_userconfig_normalize_and_validate():
    uc = UserConfig.from_dict(
        {
            "username": "  Grace  ",
            "channels": ["#Grace", "grace", "GRACE"],
            "access_token": "r" * 30,
        }
    )
    changed = uc.normalize()
    assert changed is True
    assert uc.username == "Grace".strip()
    assert uc.channels == ["grace"]
    assert uc.validate() is True


def test_invalid_userconfig_validate():
    uc = UserConfig.from_dict({"username": "ab", "channels": ["ab"], "access_token": "x" * 30})
    assert uc.validate() is False
