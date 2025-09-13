"""Color change orchestration service.

Extracted from the legacy top-level module `color_change_service.py` and now
packaged under `color`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

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
            logging.error(f"💥 Error changing color user={self.bot.username}: {str(e)}")
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
        logging.error(
            f"💥 Internal error changing {'preset ' if is_preset else ''}color user={self.bot.username}"
        )
        return False

    def _on_rate_limited(self, is_preset: bool, status_code: int) -> bool:
        self.bot.rate_limiter.handle_429_error({}, is_user_request=True)
        if not is_preset:
            logging.warning(f"⏳ Rate limited retry soon user={self.bot.username}")
        else:
            logging.warning(
                f"❌ Preset color change failed status={status_code} user={self.bot.username}"
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
        logging.info(
            f"🔐 Attempting token refresh after 401 {'preset ' if is_preset else ''}color change user={self.bot.username}"
        )
        if await self.bot._check_and_refresh_token(force=True):
            logging.info(
                f"🔄 Retrying {'preset ' if is_preset else ''}color change after token refresh user={self.bot.username}"
            )
            return await self._perform_color_change(
                color,
                allow_refresh=False,
                fallback_to_preset=fallback_to_preset,
            )
        logging.error(
            f"💥 Token refresh failed cannot retry {'preset ' if is_preset else ''}color change user={self.bot.username}"
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
            logging.warning(
                f"⚠️ Late {'preset ' if is_preset else ''}color success classification status={status_code} user={self.bot.username}"
            )
            # self.bot.last_color may be None; using `or ""` guarantees a str.
            return self._on_success(self.bot.last_color or "", is_preset)
        logging.error(
            f"{'❌ Failed to change color status' if not is_preset else '💥 Preset color change failed after retries status'}={status_code} user={self.bot.username}"
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

        logging.info(
            f"🚫 Hex color rejected status={status_code} strikes={strikes} user={self.bot.username} snippet={snippet}"
        )

        if strikes >= 2 and getattr(self.bot, "use_random_colors", False):
            try:
                self.bot.use_random_colors = False
            except Exception as e:  # noqa: BLE001
                # Log instead of silently swallowing to satisfy linting and observability
                logging.warning(
                    f"⚠️ Error during persistent hex disable user={self.bot.username}: {str(e)}",
                    exc_info=True,
                )
            logging.info(
                f"🧩 Persistent detection: disabling random hex for user={self.bot.username}"
            )
            try:
                hook = getattr(self.bot, "on_persistent_prime_detection", None)
                if hook and callable(hook):
                    res = hook()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:  # noqa: BLE001
                logging.warning(
                    f"⚠️ Error during persistent hex disable user={self.bot.username}: {str(e)}"
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
                logging.debug(
                    f"♻️ Hex color rejection strikes reset user={self.bot.username}"
                )
            except Exception:  # noqa: BLE001
                # Use existing template at WARN level and include exception context
                logging.warning(
                    f"♻️ Hex color rejection strikes reset user={self.bot.username}",
                    exc_info=True,
                )
        logging.info(f"🎨 Color changed to {color} for the user {self.bot.username}")
