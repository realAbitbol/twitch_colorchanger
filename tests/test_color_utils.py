from __future__ import annotations

import re

from src.color.utils import (
    TWITCH_PRESET_COLORS,
    get_random_hex,
    get_random_preset,
)


def test_get_random_preset_exclude_single() -> None:
    # Excluding a single valid color should never return it (probabilistic but near certain over iterations)
    excluded = TWITCH_PRESET_COLORS[0]
    for _ in range(50):
        c = get_random_preset(excluded)
        if c == excluded:
            raise AssertionError("Excluded color was returned")


def test_get_random_preset_exclude_all_fallback() -> None:
    # Excluding all should fall back to full list and still return a valid preset
    all_colors = list(TWITCH_PRESET_COLORS)
    got = get_random_preset(all_colors)
    if got not in TWITCH_PRESET_COLORS:
        raise AssertionError("Returned color not in preset list after fallback")


def test_get_random_hex_format_and_exclusion() -> None:
    # Basic property checks: #rrggbb format and exclusion honored
    bad = "#ffffff"
    for _ in range(20):
        c = get_random_hex(exclude=bad)
        if not re.fullmatch(r"#[0-9a-f]{6}", c):
            raise AssertionError(f"Hex color not in expected format: {c}")
        if c.lower() == bad:
            raise AssertionError("Excluded hex value was returned")
