"""TokenRefresher mixin for TwitchColorBot - handles token refresh and persistence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..api.twitch import TwitchAPI
from ..application_context import ApplicationContext
from ..chat import EventSubChatBackend
from ..config.async_persistence import async_update_user_in_config, queue_user_update
from ..config.model import normalize_channels_list
from ..errors.handling import handle_api_error


class TokenRefresher:
    """Mixin class for handling token refresh and configuration persistence."""

    # Expected attributes from consumer class
    username: str
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    token_expiry: datetime | None
    context: ApplicationContext
    chat_backend: EventSubChatBackend | None
    channels: list[str]
    config_file: str | None
    use_random_colors: bool
    token_manager: Any  # Set in _setup_token_manager
    """Mixin class for handling token refresh and configuration persistence."""

    def _setup_token_manager(self) -> bool:
        """Set up and register with token manager. Returns False on failure."""
        # ApplicationContext guarantees a token_manager; still guard defensively
        self.token_manager = self.context.token_manager
        if self.token_manager is None:  # pragma: no cover - defensive
            logging.error(f"❌ No token manager available user={self.username}")
            return False
        # Register credentials with the token manager
        self.token_manager._upsert_token_info(  # noqa: SLF001
            username=self.username,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=self.token_expiry,
        )
        logging.debug(f"📝 Token manager: registered user={self.username}")
        try:
            self.token_manager.register_update_hook(
                self.username, self._persist_token_changes
            )
        except Exception as e:
            logging.debug(f"Token hook registration failed: {str(e)}")
        return True

    async def _handle_initial_token_refresh(self) -> None:
        """Handle initial token refresh and persistence."""
        if self.token_manager is None:
            raise RuntimeError("Token manager not initialized")
        outcome = await self.token_manager.ensure_fresh(self.username)
        if not outcome:
            return
        info = self.token_manager.get_info(self.username)
        if not info:
            return
        old_access = self.access_token
        old_refresh = getattr(self, "refresh_token", None)
        self.access_token = info.access_token
        if getattr(info, "refresh_token", None):
            self.refresh_token = info.refresh_token
        access_changed = bool(info.access_token and info.access_token != old_access)
        refresh_changed = bool(
            getattr(info, "refresh_token", None) and info.refresh_token != old_refresh
        )
        if access_changed or refresh_changed:
            try:
                await self._persist_token_changes()
            except Exception as e:
                logging.debug(f"Token persistence error: {str(e)}")

    async def _log_scopes_if_possible(self) -> None:
        """Log the scopes of the current access token if possible.

        Validates the token with Twitch API and logs the associated scopes.
        Silently handles validation failures.
        """
        if not self.context.session:
            return
        api = TwitchAPI(self.context.session)

        async def operation():
            return await api.validate_token(self.access_token)

        try:
            validation = await handle_api_error(operation, "Token scope validation")
            raw_scopes = (
                validation.get("scopes") if isinstance(validation, dict) else None
            )
            scopes_list = (
                [str(s) for s in raw_scopes] if isinstance(raw_scopes, list) else []
            )
            logging.info(
                f"🧪 Token scopes user={self.username} scopes={';'.join(scopes_list) if scopes_list else '<none>'}"
            )
        except Exception:
            logging.debug(f"🚫 Token scope validation error user={self.username}")

    async def _normalize_channels_if_needed(self) -> list[str]:
        """Normalize channel names and persist if changed.

        Applies channel normalization rules and updates config if necessary.

        Returns:
            List of normalized channel names.
        """
        normalized_channels, was_changed = normalize_channels_list(self.channels)
        if was_changed:
            logging.info(
                f"🛠️ Normalized channels old={len(self.channels)} new={len(normalized_channels)} user={self.username}"
            )
            self.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.channels = normalized_channels
        return normalized_channels

    async def _check_and_refresh_token(self, force: bool = False) -> bool:
        """Check and refresh the access token if needed.

        Ensures the token is fresh and updates the backend if token changed.

        Args:
            force: Force token refresh even if not expired.

        Returns:
            True if token is valid/fresh, False otherwise.
        """
        # Use attached TokenManager if available; otherwise fall back to context
        tm = self.token_manager or getattr(self.context, "token_manager", None)
        if not tm:
            return False
        # Cache for subsequent calls
        self.token_manager = tm
        try:
            outcome = await tm.ensure_fresh(self.username, force_refresh=force)
            info = tm.get_info(self.username)
            if info and info.access_token:
                if info.access_token != self.access_token:
                    self.access_token = info.access_token
                    backend_local = self.chat_backend
                    if backend_local is not None:
                        try:
                            backend_local.update_token(info.access_token)
                        except Exception as e:
                            logging.debug(f"Backend token update error: {str(e)}")
                return outcome.name != "FAILED"
            return False
        except Exception as e:
            logging.error(f"Token refresh error: {str(e)}")
            return False

    async def _persist_token_changes(self) -> None:
        """Persist updated token information to configuration."""
        if not self._validate_config_prerequisites():
            return
        user_config = self._build_user_config()
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):
                return

    async def _persist_normalized_channels(self) -> None:
        """Persist normalized channel list to configuration."""
        config_file = getattr(self, "config_file", None)
        if config_file is None:
            return
        user_config = self._build_user_config()
        # Overwrite channels explicitly
        user_config["channels"] = self.channels
        try:
            await queue_user_update(user_config, config_file)
        except Exception as e:
            logging.warning(f"Persist channels error: {str(e)}")

    def _validate_config_prerequisites(self) -> bool:
        """Validate that required config fields are present for persistence.

        Returns:
            True if all prerequisites are met.
        """
        if not getattr(self, "config_file", None):
            logging.warning(
                f"📁 No config file specified cannot persist tokens user={self.username}"
            )
            return False
        if not getattr(self, "access_token", None):
            logging.warning(f"⚠️ Cannot save empty access token user={self.username}")
            return False
        if not getattr(self, "refresh_token", None):
            logging.warning(f"⚠️ Cannot save empty refresh token user={self.username}")
            return False
        return True

    def _build_user_config(self) -> dict[str, Any]:
        """Build user configuration dict from current instance state.

        Returns:
            Dict containing all user configuration fields.
        """
        # Direct attribute access; mixin consumer guarantees these attributes.
        username = self.username
        channels = self.channels
        return {
            "username": username,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "channels": channels,
            "is_prime_or_turbo": self.use_random_colors,
            "enabled": getattr(self, "enabled", True),
        }

    async def _attempt_config_save(
        self, user_config: dict[str, Any], attempt: int, max_retries: int
    ) -> bool:
        """Attempt to save user config with error handling.

        Args:
            user_config: Configuration dict to save.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            True if save was successful.
        """
        config_file = self.config_file
        if config_file is None:
            return False
        try:
            success = await async_update_user_in_config(user_config, config_file)
            if success:
                logging.debug(f"💾 Token changes saved user={self.username}")
                return True
            # Fall through to generic handling below to trigger retries
            raise RuntimeError("update_user_in_config returned False")
        except FileNotFoundError:
            logging.error(
                f"📁 Config file not found path={self.config_file} user={self.username}"
            )
            return True
        except PermissionError:
            logging.error(f"🔒 Permission denied writing config user={self.username}")
            return True
        except Exception as e:
            return await self._handle_config_save_error(e, attempt, max_retries)

    async def _handle_config_save_error(
        self, error: Exception, attempt: int, max_retries: int
    ) -> bool:
        """Handle config save errors with retry logic.

        Args:
            error: The exception that occurred.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            True if should stop retrying, False to retry.
        """
        if attempt < max_retries - 1:
            logging.warning(f"Config save retry {attempt + 1}: {str(error)}")
            await asyncio.sleep(0.1 * (attempt + 1))
            return False
        else:
            logging.error(
                f"Config save failed after {max_retries} attempts: {str(error)}"
            )
            return True
