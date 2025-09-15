"""Color utilities for Twitch preset and random hex generation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from secrets import SystemRandom

from ..constants import (
    COLOR_HUE_SECTOR_SIZE,
    COLOR_MAX_HUE,
    COLOR_MAX_LIGHTNESS,
    COLOR_MAX_SATURATION,
    COLOR_MIN_LIGHTNESS,
    COLOR_MIN_SATURATION,
    COLOR_RANDOM_HEX_MAX_ATTEMPTS,
    COLOR_RGB_MAX_VALUE,
)

__all__ = ["get_random_preset", "get_random_hex", "TWITCH_PRESET_COLORS"]

_RNG = SystemRandom()

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
    """Filter out excluded colors from a list.

    Args:
        colors (Sequence[str]): The list of colors to filter.
        exclude (Iterable[str] | None): Colors to exclude.

    Returns:
        list[str]: Filtered list of colors.
    """
    if not exclude:
        return list(colors)
    exclude_set = {e.lower() for e in exclude if e}
    return [c for c in colors if c.lower() not in exclude_set]


def get_random_preset(exclude: str | Iterable[str] | None = None) -> str:
    """Return a random Twitch preset color.

    Args:
        exclude (str | Iterable[str] | None): Colors to exclude. Can be a single color or iterable.

    Returns:
        str: A random preset color, excluding specified colors if possible.
    """
    if isinstance(exclude, str):
        excl_iter: Iterable[str] | None = [exclude]
    else:
        excl_iter = exclude
    candidates = _filter_exclude(TWITCH_PRESET_COLORS, excl_iter)
    if not candidates:
        candidates = list(TWITCH_PRESET_COLORS)
    # Non-cryptographic selection acceptable; using SystemRandom for clarity.
    return _RNG.choice(candidates)


def get_random_hex(exclude: str | Iterable[str] | None = None) -> str:
    """Generate a visually pleasing random hex color using HSL strategy.

    Args:
        exclude (str | Iterable[str] | None): Colors to exclude.

    Returns:
        str: A random hex color string.
    """
    if isinstance(exclude, str):
        exclude_set = {exclude.lower()}
    elif exclude:
        exclude_set = {e.lower() for e in exclude if e}
    else:
        exclude_set = set()

    for _ in range(COLOR_RANDOM_HEX_MAX_ATTEMPTS):
        hue = _RNG.randint(0, COLOR_MAX_HUE)
        saturation = _RNG.randint(COLOR_MIN_SATURATION, COLOR_MAX_SATURATION)
        lightness = _RNG.randint(COLOR_MIN_LIGHTNESS, COLOR_MAX_LIGHTNESS)
        c = (1 - abs(2 * lightness / 100 - 1)) * saturation / 100
        x = c * (1 - abs((hue / COLOR_HUE_SECTOR_SIZE) % 2 - 1))
        m = lightness / 100 - c / 2
        r: float
        g: float
        b: float
        if 0 <= hue < COLOR_HUE_SECTOR_SIZE:
            r, g, b = c, x, 0.0
        elif COLOR_HUE_SECTOR_SIZE <= hue < 120:
            r, g, b = x, c, 0.0
        elif 120 <= hue < 180:
            r, g, b = 0.0, c, x
        elif 180 <= hue < 240:
            r, g, b = 0.0, x, c
        elif 240 <= hue < 300:
            r, g, b = x, 0.0, c
        else:
            r, g, b = c, 0.0, x
        r_i = int((r + m) * COLOR_RGB_MAX_VALUE)
        g_i = int((g + m) * COLOR_RGB_MAX_VALUE)
        b_i = int((b + m) * COLOR_RGB_MAX_VALUE)
        color = f"#{r_i:02x}{g_i:02x}{b_i:02x}"
        if color.lower() not in exclude_set:
            return color
    return color
