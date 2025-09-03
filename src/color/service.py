"""Color change orchestration service.

Extracted from the legacy top-level module `color_change_service.py` and now
packaged under `color`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_logging.logger import logger
from rate.retry_policies import COLOR_CHANGE_RETRY, run_with_retry

from .utils import get_random_hex, get_random_preset

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
                    color,
                    allow_refresh=True,
                    fallback_to_preset=allow_fallback,
                    action="change_color",
                    is_preset=False,
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
        allow_refresh: bool,
        fallback_to_preset: bool,
        action: str,
        is_preset: bool,
    ) -> bool:
        status_code = await self._issue_request(color, action)

        if status_code == 204:
            return self._on_success(color, is_preset)
        if status_code == 0:
            return self._on_internal_error(is_preset)
        if status_code == 429:
            return self._on_rate_limited(is_preset, status_code)
        if status_code == 401:
            return await self._on_unauthorized(
                color,
                allow_refresh=allow_refresh,
                fallback_to_preset=fallback_to_preset,
                action=action,
                is_preset=is_preset,
            )
        return await self._on_generic_failure(
            is_preset=is_preset,
            status_code=status_code,
            fallback_to_preset=fallback_to_preset,
        )

    async def _issue_request(self, color: str, action: str) -> int:
        params = {"user_id": self.bot.user_id, "color": color}
        return await self.bot._perform_color_request(params, action=action)

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
        action: str,
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
                action=action,
                is_preset=is_preset,
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
                action="preset_color",
                is_preset=True,
            )
        return False

    def _select_color(self) -> str:
        if self.bot.use_random_colors:
            return get_random_hex(exclude=self.bot.last_color)
        return get_random_preset(exclude=self.bot.last_color)

    def _record_success(self, color: str, is_preset: bool) -> None:
        self.bot.increment_colors_changed()
        self.bot.last_color = color
        logger.log_event(
            "bot",
            "color_changed" if not is_preset else "preset_color_changed",
            user=self.bot.username,
            color=color,
        )
