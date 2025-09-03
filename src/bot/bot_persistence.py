"""Persistence helpers extracted from `bot.TwitchColorBot`.

Provides a mixin with config/token persistence related methods to reduce
`bot.py` file size and isolate concerns.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from config.async_persistence import (
    async_update_user_in_config,
    queue_user_update,
)
from logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    pass


class BotPersistenceMixin:
    """Mixin that adds persistence helper methods.

    Expects the consumer class to define:
      - username, access_token, refresh_token, client_id, client_secret
      - config_file, channels, use_random_colors, enabled
    """

    # --- Public entry points used by bot ---
    async def _persist_token_changes(self):  # type: ignore[no-untyped-def]
        if not self._validate_config_prerequisites():  # type: ignore[attr-defined]
            return
        user_config = self._build_user_config()  # type: ignore[attr-defined]
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):  # type: ignore[attr-defined]
                return

    async def _persist_normalized_channels(self):  # type: ignore[no-untyped-def]
        if hasattr(self, "config_file") and self.config_file:  # type: ignore[attr-defined]
            user_config = self._build_user_config()  # type: ignore[attr-defined]
            # Overwrite channels explicitly
            user_config["channels"] = self.channels  # type: ignore[attr-defined]
            try:
                # Debounced write; normalization may happen in bursts.
                await queue_user_update(
                    user_config,
                    self.config_file,  # type: ignore[attr-defined]
                )
                logger.log_event("bot", "normalized_channels_saved", user=self.username)  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "bot",
                    "normalized_channels_save_failed",
                    level=30,
                    user=self.username,  # type: ignore[attr-defined]
                    error=str(e),
                )

    # --- Internal helpers ---
    def _validate_config_prerequisites(self) -> bool:  # type: ignore[no-untyped-def]
        if not hasattr(self, "config_file") or not self.config_file:  # type: ignore[attr-defined]
            logger.log_event(
                "bot",
                "no_config_file_for_persist",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        if not self.access_token:  # type: ignore[attr-defined]
            logger.log_event(
                "bot",
                "empty_access_token",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        if not self.refresh_token:  # type: ignore[attr-defined]
            logger.log_event(
                "bot",
                "empty_refresh_token",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        return True

    def _build_user_config(self) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        return {
            "username": self.username,  # type: ignore[attr-defined]
            "client_id": self.client_id,  # type: ignore[attr-defined]
            "client_secret": self.client_secret,  # type: ignore[attr-defined]
            "access_token": self.access_token,  # type: ignore[attr-defined]
            "refresh_token": self.refresh_token,  # type: ignore[attr-defined]
            "channels": getattr(self, "channels", [self.username.lower()]),  # type: ignore[attr-defined]
            "is_prime_or_turbo": self.use_random_colors,  # type: ignore[attr-defined]
            "enabled": getattr(self, "enabled", True),  # type: ignore[attr-defined]
        }

    async def _attempt_config_save(  # type: ignore[no-untyped-def]
        self, user_config: dict, attempt: int, max_retries: int
    ) -> bool:
        try:
            success = await async_update_user_in_config(  # type: ignore[attr-defined]
                user_config,
                self.config_file,  # type: ignore[attr-defined]
            )
            if success:
                logger.log_event("bot", "token_saved", user=self.username)  # type: ignore[attr-defined]
                return True
            # Fall through to generic handling below to trigger retries
            raise RuntimeError("update_user_in_config returned False")
        except FileNotFoundError:
            logger.log_event(
                "bot",
                "config_file_not_found",
                level=40,
                user=self.username,  # type: ignore[attr-defined]
                path=self.config_file,  # type: ignore[attr-defined]
            )
            return True
        except PermissionError:
            logger.log_event(
                "bot",
                "config_permission_denied",
                level=40,
                user=self.username,  # type: ignore[attr-defined]
            )
            return True
        except Exception as e:  # noqa: BLE001
            return await self._handle_config_save_error(e, attempt, max_retries)  # type: ignore[attr-defined]

    async def _handle_config_save_error(  # type: ignore[no-untyped-def]
        self, error: Exception, attempt: int, max_retries: int
    ) -> bool:
        if attempt < max_retries - 1:
            logger.log_event(
                "bot",
                "save_retry",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
                attempt=attempt + 1,
                error=str(error),
            )
            await asyncio.sleep(0.1 * (attempt + 1))
            return False
        else:
            logger.log_event(
                "bot",
                "save_failed_final",
                level=40,
                user=self.username,  # type: ignore[attr-defined]
                attempts=max_retries,
                error=str(error),
            )
            return True
