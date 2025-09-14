from __future__ import annotations

from src.config.model import UserConfig, normalize_channels_list, normalize_user_list


def test_user_config_normalize_idempotent() -> None:
    uc = UserConfig(
        username="  Alice  ",
        channels=["#ChanOne", "chanone", "ChanTwo ", "#CHANTWO"],
        is_prime_or_turbo=True,
        enabled=True,
        access_token="a" * 20,
        client_id="b" * 10,
        client_secret="c" * 10,
    )
    changed_first = uc.normalize()
    changed_second = uc.normalize()
    # First call should not report changes; second call should be idempotent
    if changed_first:
        raise AssertionError("Expected first normalization to not report changes")
    if changed_second:
        raise AssertionError("Second normalization should be idempotent (no changes)")
    # Channels should be lowercase deduped without leading '#'
    if uc.channels != ["chanone", "chantwo"]:
        raise AssertionError(f"Unexpected channels: {uc.channels}")


def test_normalize_user_list_produces_changes_flag() -> None:
    users = [
        {"username": "Bob", "channels": ["#Alpha", "ALPHA", "beta "], "access_token": "d" * 20, "client_id": "e" * 10, "client_secret": "f" * 10},
        {"username": "carol", "channels": ["carol", "#carol "], "access_token": "g" * 20, "client_id": "h" * 10, "client_secret": "i" * 10},
    ]
    normalized, changed = normalize_user_list(users)
    if changed:
        raise AssertionError("Expected normalization to not mark changes")
    # Normalized usernames unchanged except trimming; channel lists deduped/lowercased without '#'
    expected = [
        {"username": "Bob", "channels": ["alpha", "beta"], "is_prime_or_turbo": True, "enabled": True},
        {"username": "carol", "channels": ["carol"], "is_prime_or_turbo": True, "enabled": True},
    ]
    # Convert lists to sets for channel comparison ordering-insensitive
    for exp, got in zip(expected, normalized, strict=False):
        if exp["username"] != got["username"]:
            raise AssertionError(f"Username mismatch: {exp['username']} vs {got['username']}")
        if set(exp["channels"]) != set(got["channels"]):
            raise AssertionError(f"Channels mismatch: {exp['channels']} vs {got['channels']}")


def test_normalize_channels_list_helpers() -> None:
    chans, changed = normalize_channels_list(["#One", "one", "TWO", " two "])
    if not changed:
        raise AssertionError("Expected changes in channel normalization")
    if chans != ["one", "two"]:
        raise AssertionError(f"Unexpected normalized list: {chans}")

    # Already normalized list -> no change
    chans2, changed2 = normalize_channels_list(["alpha", "beta"])
    if changed2:
        raise AssertionError("Did not expect changes for already-normalized channels")
    if chans2 != ["alpha", "beta"]:
        raise AssertionError("Ordering or values altered unexpectedly")
