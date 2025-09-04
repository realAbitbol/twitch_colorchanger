"""Persistence helpers extracted from `bot.TwitchColorBot`.

Provides a mixin with config/token persistence related methods to reduce
`bot.py` file size and isolate concerns.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..config.async_persistence import (
    async_update_user_in_config,
    queue_user_update,
)
from ..logs.logger import logger

if TYPE_CHECKING:  # pragma: no cover
    pass


@runtime_checkable
class _PersistenceConsumer(Protocol):
    username: str
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    channels: list[str]
    use_random_colors: bool
    enabled: bool
    config_file: str | None


class BotPersistenceMixin:
    """Mixin that adds persistence helper methods.

    Expects the consumer class to define:
      - username, access_token, refresh_token, client_id, client_secret
      - config_file, channels, use_random_colors, enabled
    """

    # --- Public entry points used by bot ---
    async def _persist_token_changes(self) -> None:
        if not self._validate_config_prerequisites():
            return
        user_config = self._build_user_config()
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):
                return

    async def _persist_normalized_channels(self) -> None:
        if getattr(self, "config_file", None):
            user_config = self._build_user_config()
            # Overwrite channels explicitly
            user_config["channels"] = self.channels  # type: ignore[attr-defined]  # channels attr guaranteed by consumer
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
    def _validate_config_prerequisites(self) -> bool:
        if not getattr(self, "config_file", None):
            logger.log_event(
                "bot",
                "no_config_file_for_persist",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        if not getattr(self, "access_token", None):
            logger.log_event(
                "bot",
                "empty_access_token",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        if not getattr(self, "refresh_token", None):
            logger.log_event(
                "bot",
                "empty_refresh_token",
                level=30,
                user=self.username,  # type: ignore[attr-defined]
            )
            return False
        return True

    def _build_user_config(self) -> dict[str, Any]:
        # Direct attribute access; mixin consumer guarantees these attributes.
        username = self.username  # type: ignore[attr-defined]
        # channels attribute guaranteed by consumer; fallback only if absent (legacy bots)
        channels = getattr(self, "channels", [username.lower()])
        return {
            "username": username,
            "client_id": self.client_id,  # type: ignore[attr-defined]
            "client_secret": self.client_secret,  # type: ignore[attr-defined]
            "access_token": self.access_token,  # type: ignore[attr-defined]
            "refresh_token": self.refresh_token,  # type: ignore[attr-defined]
            "channels": channels,
            "is_prime_or_turbo": self.use_random_colors,  # type: ignore[attr-defined]
            "enabled": getattr(self, "enabled", True),
        }

    async def _attempt_config_save(
        self, user_config: dict[str, Any], attempt: int, max_retries: int
    ) -> bool:
        try:
            success = await async_update_user_in_config(user_config, self.config_file)  # type: ignore[attr-defined]
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
            return await self._handle_config_save_error(e, attempt, max_retries)

    async def _handle_config_save_error(
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
