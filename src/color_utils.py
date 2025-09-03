"""Color utilities for Twitch preset and random hex generation."""

from __future__ import annotations

import random  # nosec B311
from collections.abc import Iterable, Sequence

__all__ = ["get_random_preset", "get_random_hex", "TWITCH_PRESET_COLORS"]

TWITCH_PRESET_COLORS: Sequence[str] = (
    "blue",
    "blue_violet",
    "cadet_blue",
    "chocolate",
    "coral",
    "dodger_blue",
    "firebrick",
    "golden_rod",
    "green",
    "hot_pink",
    "orange_red",
    "red",
    "sea_green",
    "spring_green",
    "yellow_green",
)


def _filter_exclude(colors: Sequence[str], exclude: Iterable[str] | None) -> list[str]:
    if not exclude:
        return list(colors)
    exclude_set = {e.lower() for e in exclude if e}
    return [c for c in colors if c.lower() not in exclude_set]


def get_random_preset(exclude: str | Iterable[str] | None = None) -> str:
    """Return a random Twitch preset color.

    exclude can be a single color or iterable of colors to avoid.
    Falls back to full list if exclusion removes all options.
    """
    if isinstance(exclude, str):
        excl_iter: Iterable[str] | None = [exclude]
    else:
        excl_iter = exclude
    candidates = _filter_exclude(TWITCH_PRESET_COLORS, excl_iter)
    if not candidates:
        candidates = list(TWITCH_PRESET_COLORS)
    return random.choice(candidates)  # nosec B311


def get_random_hex(exclude: str | Iterable[str] | None = None) -> str:
    """Generate a visually pleasing random hex color (HSL strategy)."""
    if isinstance(exclude, str):
        exclude_set = {exclude.lower()}
    elif exclude:
        exclude_set = {e.lower() for e in exclude if e}
    else:
        exclude_set = set()

    for _ in range(10):
        hue = random.randint(0, 359)  # nosec B311
        saturation = random.randint(60, 100)  # nosec B311
        lightness = random.randint(35, 75)  # nosec B311
        c = (1 - abs(2 * lightness / 100 - 1)) * saturation / 100
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = lightness / 100 - c / 2
        r: float
        g: float
        b: float
        if 0 <= hue < 60:
            r, g, b = c, x, 0.0
        elif 60 <= hue < 120:
            r, g, b = x, c, 0.0
        elif 120 <= hue < 180:
            r, g, b = 0.0, c, x
        elif 180 <= hue < 240:
            r, g, b = 0.0, x, c
        elif 240 <= hue < 300:
            r, g, b = x, 0.0, c
        else:
            r, g, b = c, 0.0, x
        r_i = int((r + m) * 255)
        g_i = int((g + m) * 255)
        b_i = int((b + m) * 255)
        color = f"#{r_i:02x}{g_i:02x}{b_i:02x}"
        if color.lower() not in exclude_set:
            return color
    return color
