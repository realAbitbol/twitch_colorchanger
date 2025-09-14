"""Service for handling Twitch color change operations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from .models import ColorRequestResult, ColorRequestStatus
from .utils import TWITCH_PRESET_COLORS, get_random_hex, get_random_preset

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot


class ColorChangeService:
    """Service for managing Twitch color changes.

    Handles color change requests, retries, fallbacks, and error handling.
    """

    def __init__(self, bot: TwitchColorBot) -> None:
        """Initialize the color change service.

        Args:
            bot (TwitchColorBot): The bot instance to perform color changes on.
        """
        if bot is None:
            raise TypeError("bot cannot be None")
        self.bot = bot

    async def change_color(self, hex_color: str | None = None) -> bool:
        """Change the bot's color to the specified hex or a random color.

        Args:
            hex_color (str | None): Specific hex color to change to, or None for random.

        Returns:
            bool: True if the color change was successful, False otherwise.
        """
        if hex_color:
            color = hex_color
            allow_fallback = False
        else:
            color = self._select_color()
            allow_fallback = self.bot.use_random_colors

        try:
            return await self._perform_color_change(
                color, allow_refresh=True, fallback_to_preset=allow_fallback
            )
        except Exception as e:
            logging.error(f"Error changing color: {str(e)}")
            return False

    async def _perform_color_change(
        self,
        color: str,
        *,
        allow_refresh: bool = True,
        fallback_to_preset: bool = True,
    ) -> bool:
        """Perform the core color change operation with retry and status handling.

        Args:
            color (str): Target color (hex like #aabbcc or preset name).
            allow_refresh (bool): Whether a 401 triggers a token refresh attempt.
            fallback_to_preset (bool): Whether to fall back to preset on non-preset failure.

        Returns:
            bool: True if successful, False otherwise.
        """
        # Determine if this is a preset color (case-insensitive lookup)
        lowered = color.lower()
        is_preset = lowered in {c.lower() for c in TWITCH_PRESET_COLORS}
        action = "preset_color" if is_preset else "change_color"

        result = await self._issue_request(color, action)

        if result.status == ColorRequestStatus.SUCCESS:
            return self._on_success(color, is_preset)
        if result.status in (
            ColorRequestStatus.TIMEOUT,
            ColorRequestStatus.INTERNAL_ERROR,
        ):
            return self._on_internal_error()
        if result.status == ColorRequestStatus.RATE_LIMIT:
            return self._on_rate_limited(result.http_status or 429)
        if result.status == ColorRequestStatus.UNAUTHORIZED:
            return await self._on_unauthorized(
                color,
                allow_refresh=allow_refresh,
                fallback_to_preset=fallback_to_preset,
            )
        return await self._on_generic_failure(
            is_preset=is_preset,
            status_code=result.http_status or 0,
            fallback_to_preset=fallback_to_preset,
        )

    async def _issue_request(self, color: str, action: str) -> ColorRequestResult:
        """Issue a color change request to the bot.

        Args:
            color (str): The color to change to.
            action (str): The action type for the request.

        Returns:
            ColorRequestResult: The result of the request.
        """
        params = {"user_id": self.bot.user_id, "color": color}
        # _perform_color_request is defined on the bot and returns a ColorRequestResult
        # but lacks a precise return annotation; cast here to satisfy typing.
        return cast(
            ColorRequestResult,
            await self.bot._perform_color_request(params, action=action),
        )

    def _on_success(self, color: str, is_preset: bool) -> bool:
        """Handle successful color change.

        Args:
            color (str): The color that was changed to.
            is_preset (bool): Whether the color is a preset.

        Returns:
            bool: Always True.
        """
        self._record_success(color, is_preset)
        return True

    def _on_internal_error(self) -> bool:
        """Handle internal error during color change.

        Returns:
            bool: Always False.
        """
        logging.error("Internal error changing color")
        return False

    def _on_rate_limited(self, status_code: int) -> bool:
        """Handle rate limit error.

        Args:
            status_code (int): The HTTP status code.

        Returns:
            bool: Always False.
        """
        logging.warning(f"Rate limited: {status_code}")
        return False

    async def _on_unauthorized(
        self,
        color: str,
        *,
        allow_refresh: bool,
        fallback_to_preset: bool,
    ) -> bool:
        """Handle unauthorized error, attempting token refresh.

        Args:
            color (str): The color being changed to.
            allow_refresh (bool): Whether to allow token refresh.
            fallback_to_preset (bool): Whether to fallback to preset.

        Returns:
            bool: True if retry succeeds, False otherwise.
        """
        if not allow_refresh:
            return False
        if await self.bot._check_and_refresh_token(force=True):
            return await self._perform_color_change(
                color,
                allow_refresh=False,
                fallback_to_preset=fallback_to_preset,
            )
        return False

    async def _on_generic_failure(
        self,
        *,
        is_preset: bool,
        status_code: int,
        fallback_to_preset: bool,
    ) -> bool:
        """Handle generic failure, with fallback logic.

        Args:
            is_preset (bool): Whether the color is a preset.
            status_code (int): The HTTP status code.
            fallback_to_preset (bool): Whether to fallback to preset.

        Returns:
            bool: True if fallback succeeds, False otherwise.
        """
        # Persistent Turbo/Prime detection: track repeated hex rejections
        if not is_preset and status_code in (400, 403):
            await self._handle_hex_rejection(status_code)
        if 200 <= status_code < 300:
            return self._on_success(self.bot.last_color or "", is_preset)
        logging.error(f"Failed to change color: {status_code}")
        if fallback_to_preset and not is_preset:
            preset = get_random_preset(exclude=self.bot.last_color)
            return await self._perform_color_change(
                preset,
                allow_refresh=True,
                fallback_to_preset=False,
            )
        return False

    async def _handle_hex_rejection(self, status_code: int) -> None:
        """Handle repeated hex color rejections by disabling random hex.

        After two strikes, assume lack of Turbo/Prime and disable random hex,
        then persist the change.

        Args:
            status_code (int): The rejection status code (400 or 403).
        """
        strikes = getattr(self.bot, "_hex_rejection_strikes", 0) + 1
        self.bot._hex_rejection_strikes = strikes
        logging.info(f"Hex color rejected: {status_code}, strikes: {strikes}")

        if strikes >= 2 and getattr(self.bot, "use_random_colors", False):
            self.bot.use_random_colors = False
            logging.info("Disabling random hex due to persistent rejections")
            hook = getattr(self.bot, "on_persistent_prime_detection", None)
            if hook and callable(hook):
                res = hook()
                if asyncio.iscoroutine(res):
                    await res

    def _select_color(self) -> str:
        """Select a random color based on bot settings.

        Returns:
            str: The selected color (hex or preset).
        """
        if self.bot.use_random_colors:
            return get_random_hex(exclude=self.bot.last_color)
        return get_random_preset(exclude=self.bot.last_color)

    def _record_success(self, color: str, is_preset: bool) -> None:
        """Record a successful color change.

        Args:
            color (str): The color that was changed to.
            is_preset (bool): Whether the color is a preset.
        """
        self.bot.last_color = color
        if not is_preset:
            self.bot._hex_rejection_strikes = 0
        logging.info(f"🎨 Color of {self.bot.username} changed to {color}")
