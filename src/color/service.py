"""Color change orchestration service.

Extracted from the legacy top-level module `color_change_service.py` and now
packaged under `color`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ..logs.logger import logger
from ..rate.retry_policies import COLOR_CHANGE_RETRY, run_with_retry
from .models import ColorRequestResult, ColorRequestStatus
from .utils import TWITCH_PRESET_COLORS, get_random_hex, get_random_preset

if TYPE_CHECKING:  # pragma: no cover
    from bot import TwitchColorBot


class ColorChangeService:
    def __init__(self, bot: TwitchColorBot) -> None:
        self.bot = bot

    async def change_color(self, hex_color: str | None = None) -> bool:
        if hex_color:
            color = hex_color
            allow_fallback = False
        else:
            color = self._select_color()
            allow_fallback = self.bot.use_random_colors

        try:

            async def op() -> bool:
                await self.bot.rate_limiter.wait_if_needed(
                    "change_color", is_user_request=True
                )
                return await self._perform_color_change(
                    color, allow_refresh=True, fallback_to_preset=allow_fallback
                )

            return await run_with_retry(
                op, COLOR_CHANGE_RETRY, user=self.bot.username, log_domain="retry"
            )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "error_changing_color_internal",
                level=40,
                user=self.bot.username,
                error=str(e),
            )
            return False

    async def _perform_color_change(
        self,
        color: str,
        *,
        allow_refresh: bool = True,
        fallback_to_preset: bool = True,
    ) -> bool:
        """Core color change operation with unified retry/status handling.

        Parameters
        ----------
        color: Target color (hex like #aabbcc or preset name).
        allow_refresh: Whether a 401 triggers a token refresh attempt.
        fallback_to_preset: Whether a failure on a non-preset color should fall back
            to a random preset color.
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
            return self._on_internal_error(is_preset)
        if result.status == ColorRequestStatus.RATE_LIMIT:
            return self._on_rate_limited(is_preset, result.http_status or 429)
        if result.status == ColorRequestStatus.UNAUTHORIZED:
            return await self._on_unauthorized(
                color,
                allow_refresh=allow_refresh,
                fallback_to_preset=fallback_to_preset,
                is_preset=is_preset,
            )
        return await self._on_generic_failure(
            is_preset=is_preset,
            status_code=result.http_status or 0,
            fallback_to_preset=fallback_to_preset,
        )

    async def _issue_request(self, color: str, action: str) -> ColorRequestResult:
        params = {"user_id": self.bot.user_id, "color": color}
        # _perform_color_request is defined on the bot and returns a ColorRequestResult
        # but lacks a precise return annotation; cast here to satisfy typing.
        return cast(
            ColorRequestResult,
            await self.bot._perform_color_request(params, action=action),
        )

    def _on_success(self, color: str, is_preset: bool) -> bool:
        self._record_success(color, is_preset)
        return True

    def _on_internal_error(self, is_preset: bool) -> bool:
        logger.log_event(
            "bot",
            "color_change_internal_error"
            if not is_preset
            else "preset_color_internal_error",
            level=40,
            user=self.bot.username,
        )
        return False

    def _on_rate_limited(self, is_preset: bool, status_code: int) -> bool:
        self.bot.rate_limiter.handle_429_error({}, is_user_request=True)
        logger.log_event(
            "bot",
            "rate_limited_color_change"
            if not is_preset
            else "preset_color_failed_status",
            level=30,
            user=self.bot.username,
            status_code=status_code if is_preset else None,
        )
        return False

    async def _on_unauthorized(
        self,
        color: str,
        *,
        allow_refresh: bool,
        fallback_to_preset: bool,
        is_preset: bool,
    ) -> bool:
        if not allow_refresh:
            return False
        logger.log_event(
            "bot",
            "color_change_attempt_refresh" if not is_preset else "preset_color_401",
            user=self.bot.username,
        )
        if await self.bot._check_and_refresh_token(force=True):
            logger.log_event(
                "bot",
                "color_retry_after_refresh" if not is_preset else "preset_color_retry",
                user=self.bot.username,
            )
            return await self._perform_color_change(
                color,
                allow_refresh=False,
                fallback_to_preset=fallback_to_preset,
            )
        logger.log_event(
            "bot",
            "color_refresh_failed" if not is_preset else "preset_color_refresh_failed",
            level=40,
            user=self.bot.username,
        )
        return False

    async def _on_generic_failure(
        self,
        *,
        is_preset: bool,
        status_code: int,
        fallback_to_preset: bool,
    ) -> bool:
        # Persistent Turbo/Prime detection: track repeated hex rejections
        if not is_preset and status_code in (400, 403):
            await self._handle_hex_rejection(status_code)
        # Defensive guard: if a success (2xx/204) status bubbles here due to
        # any upstream classification inconsistency, treat it as success
        # instead of emitting a false failure event (observed 204 case).
        if 200 <= status_code < 300:
            logger.log_event(
                "bot",
                "color_success_late_classification"
                if not is_preset
                else "preset_color_success_late_classification",
                level=30,
                user=self.bot.username,
                status_code=status_code,
            )
            # self.bot.last_color may be None; using `or ""` guarantees a str.
            return self._on_success(self.bot.last_color or "", is_preset)
        logger.log_event(
            "bot",
            "color_change_status_failed"
            if not is_preset
            else "preset_color_retry_failed_status",
            level=40,
            user=self.bot.username,
            status_code=status_code,
        )
        if fallback_to_preset and not is_preset:
            preset = get_random_preset(exclude=self.bot.last_color)
            return await self._perform_color_change(
                preset,
                allow_refresh=True,
                fallback_to_preset=False,
            )
        return False

    async def _handle_hex_rejection(self, status_code: int) -> None:
        """On repeated 400/403 for hex, disable random hex and persist to config.

        After two strikes, we assume lack of Turbo/Prime for hex colors and
        flip use_random_colors to False, then invoke a bot hook to persist.
        """
        try:
            strikes = int(getattr(self.bot, "_hex_rejection_strikes", 0)) + 1
            self.bot._hex_rejection_strikes = strikes
        except Exception:
            strikes = 1
            self.bot._hex_rejection_strikes = strikes

        snippet: str | None = None
        try:
            extract = getattr(self.bot, "_extract_color_error_snippet", None)
            if callable(extract):
                snippet = extract()
        except Exception:
            snippet = None

        logger.log_event(
            "bot",
            "hex_color_rejection",
            user=self.bot.username,
            status_code=status_code,
            strikes=strikes,
            snippet=snippet,
        )

        if strikes >= 2 and getattr(self.bot, "use_random_colors", False):
            try:
                self.bot.use_random_colors = False
            except Exception as e:  # noqa: BLE001
                # Log instead of silently swallowing to satisfy linting and observability
                logger.log_event(
                    "bot",
                    "hex_color_persist_disable_error",
                    level=30,
                    user=self.bot.username,
                    error=str(e),
                    exc_info=True,
                )
            logger.log_event("bot", "hex_color_persist_disable", user=self.bot.username)
            try:
                hook = getattr(self.bot, "on_persistent_prime_detection", None)
                if hook and callable(hook):
                    res = hook()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "hex_color_persist_disable_error",
                    level=30,
                    user=self.bot.username,
                    error=str(e),
                )

    def _select_color(self) -> str:
        if self.bot.use_random_colors:
            return get_random_hex(exclude=self.bot.last_color)
        return get_random_preset(exclude=self.bot.last_color)

    def _record_success(self, color: str, is_preset: bool) -> None:
        self.bot.increment_colors_changed()
        self.bot.last_color = color
        # If a true-hex color succeeded, reset any accumulated rejection strikes
        if not is_preset:
            try:
                self.bot._hex_rejection_strikes = 0
                logger.log_event(
                    "bot", "hex_color_strikes_reset", user=self.bot.username
                )
            except Exception as e:  # noqa: BLE001
                # Use existing template at WARN level and include exception context
                logger.log_event(
                    "bot",
                    "hex_color_strikes_reset",
                    level=30,
                    user=self.bot.username,
                    error=str(e),
                    exc_info=True,
                )
        logger.log_event(
            "bot",
            "color_changed" if not is_preset else "preset_color_changed",
            user=self.bot.username,
            color=color,
        )
