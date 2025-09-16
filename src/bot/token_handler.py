"""TokenHandler class for TwitchColorBot - handles token refresh and persistence."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import TwitchColorBot

import aiohttp

from ..api.twitch import TwitchAPI
from ..auth_token.provisioner import TokenProvisioner
from ..config.async_persistence import async_update_user_in_config, queue_user_update
from ..config.model import normalize_channels_list
from ..errors.handling import handle_api_error
from ..errors.internal import InternalError


class TokenHandler:
    """Handles token refresh and configuration persistence."""

    def __init__(self, bot: TwitchColorBot) -> None:
        """Initialize the token handler.

        Args:
            bot: The TwitchColorBot instance this handler belongs to.
        """
        self.bot = bot
        self._device_flow_lock = asyncio.Lock()
        self._device_flow_in_progress = False

    async def setup_token_manager(self) -> bool:
        """Set up and register with token manager. Returns False on failure."""
        # ApplicationContext guarantees a token_manager; still guard defensively
        self.bot.token_manager = self.bot.context.token_manager
        if self.bot.token_manager is None:  # pragma: no cover - defensive
            logging.error(f"❌ No token manager available user={self.bot.username}")
            return False
        if self.bot.access_token is None or self.bot.refresh_token is None:
            logging.error(f"❌ Tokens not available user={self.bot.username}")
            return False
        # Register credentials with the token manager
        await self.bot.token_manager._upsert_token_info(  # noqa: SLF001
            username=self.bot.username,
            access_token=self.bot.access_token,
            refresh_token=self.bot.refresh_token,
            client_id=self.bot.client_id,
            client_secret=self.bot.client_secret,
            expiry=self.bot.token_expiry,
        )
        logging.debug(f"📝 Token manager: registered user={self.bot.username}")
        try:
            await self.bot.token_manager.register_update_hook(
                self.bot.username, self._persist_token_changes
            )
            await self.bot.token_manager.register_invalidation_hook(
                self.bot.username, self._trigger_device_flow_reauth
            )
        except (ValueError, RuntimeError) as e:
            logging.debug(f"Token hook registration failed: {str(e)}")
        return True

    async def handle_initial_token_refresh(self) -> None:
        """Handle initial token refresh and persistence."""
        if self.bot.token_manager is None:
            raise RuntimeError("Token manager not initialized")
        outcome = await self.bot.token_manager.ensure_fresh(self.bot.username)
        if not outcome:
            return
        info = await self.bot.token_manager.get_info(self.bot.username)
        if not info:
            return
        old_access = self.bot.access_token
        old_refresh = getattr(self.bot, "refresh_token", None)
        self.bot.access_token = info.access_token
        if getattr(info, "refresh_token", None):
            self.bot.refresh_token = info.refresh_token
        self.bot.token_expiry = info.expiry
        access_changed = bool(info.access_token and info.access_token != old_access)
        refresh_changed = bool(
            getattr(info, "refresh_token", None) and info.refresh_token != old_refresh
        )
        if access_changed or refresh_changed:
            try:
                await self._persist_token_changes()
            except (OSError, ValueError, RuntimeError) as e:
                logging.debug(f"Token persistence error: {str(e)}")
        # Check required scopes on initial load
        if info.access_token and not await self._validate_required_scopes(
            info.access_token
        ):
            logging.warning(
                f"🚫 Insufficient scopes detected on initial load user={self.bot.username}, invalidating and triggering re-auth"
            )
            self.bot.access_token = None
            self.bot.refresh_token = None
            self.bot.token_expiry = None
            await self._trigger_device_flow_reauth(
                reason="insufficient scopes on initial load"
            )

    async def log_scopes_if_possible(self) -> None:
        """Log the scopes of the current access token if possible.

        Validates the token with Twitch API and logs the associated scopes.
        Silently handles validation failures.
        """
        if not self.bot.context.session:
            return
        api = TwitchAPI(self.bot.context.session)

        async def operation():
            return await api.validate_token(self.bot.access_token)

        try:
            validation = await handle_api_error(operation, "Token scope validation")
            raw_scopes = (
                validation.get("scopes") if isinstance(validation, dict) else None
            )
            scopes_list = (
                [str(s) for s in raw_scopes] if isinstance(raw_scopes, list) else []
            )
            logging.info(
                f"🧪 Token scopes user={self.bot.username} scopes={';'.join(scopes_list) if scopes_list else '<none>'}"
            )
        except (
            aiohttp.ClientError,
            TimeoutError,
            ConnectionError,
            ValueError,
            RuntimeError,
            InternalError,
        ):
            logging.debug(f"🚫 Token scope validation error user={self.bot.username}")

    async def normalize_channels_if_needed(self) -> list[str]:
        """Normalize channel names and persist if changed.

        Applies channel normalization rules and updates config if necessary.

        Returns:
            List of normalized channel names.
        """
        normalized_channels, was_changed = normalize_channels_list(self.bot.channels)
        if was_changed:
            logging.debug(
                f"🛠️ Normalized channels old={len(self.bot.channels)} new={len(normalized_channels)} user={self.bot.username}"
            )
            self.bot.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.bot.channels = normalized_channels
        return normalized_channels

    async def check_and_refresh_token(self, force: bool = False) -> bool:
        """Check and refresh the access token if needed.

        Ensures the token is fresh, validates required scopes, and updates the backend if token changed.

        Args:
            force: Force token refresh even if not expired.

        Returns:
            True if token is valid/fresh, False otherwise.
        """
        # Use attached TokenManager if available; otherwise fall back to context
        tm = self.bot.token_manager or getattr(self.bot.context, "token_manager", None)
        if not tm:
            return False
        # Cache for subsequent calls
        self.bot.token_manager = tm
        try:
            outcome = await tm.ensure_fresh(self.bot.username, force_refresh=force)
            info = await tm.get_info(self.bot.username)
            if not info or not info.access_token:
                return False
            # Validate scopes
            if not await self._validate_required_scopes(info.access_token):
                logging.warning(
                    f"🚫 Insufficient scopes detected user={self.bot.username}, triggering re-auth"
                )
                await self._trigger_device_flow_reauth(reason="insufficient scopes")
                return False
            token_changed = self._update_bot_tokens(info)
            if token_changed:
                self._update_backend_token(info.access_token)
            return outcome.name != "FAILED"
        except (aiohttp.ClientError, ValueError, RuntimeError) as e:
            logging.error(f"Token refresh error: {str(e)}")
            return False

    def _update_bot_tokens(self, info) -> bool:
        """Update bot's tokens if they have changed.

        Args:
            info: Token info from token manager.

        Returns:
            True if any token was updated, False otherwise.
        """
        changed = False
        if info.access_token != self.bot.access_token:
            self.bot.access_token = info.access_token
            changed = True
        if getattr(info, "refresh_token", None) and info.refresh_token != getattr(
            self.bot, "refresh_token", None
        ):
            self.bot.refresh_token = info.refresh_token
            changed = True
        if info.expiry != self.bot.token_expiry:
            self.bot.token_expiry = info.expiry
            changed = True
        return changed

    def _update_backend_token(self, access_token: str) -> None:
        """Update the backend with the new access token.

        Args:
            access_token: The new access token.
        """
        backend_local = self.bot.connection_manager.chat_backend
        if backend_local is not None:
            try:
                backend_local.update_token(access_token)
            except (AttributeError, ValueError, RuntimeError) as e:
                logging.debug(f"Backend token update error: {str(e)}")

    async def _validate_required_scopes(self, access_token: str) -> bool:
        """Validate that the access token has the required scopes.

        Args:
            access_token: The access token to validate.

        Returns:
            True if all required scopes are present, False otherwise.
        """
        if not self.bot.context.session:
            return False
        api = TwitchAPI(self.bot.context.session)
        required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}
        try:
            validation = await api.validate_token(access_token)
            if not isinstance(validation, dict):
                return False
            raw_scopes = validation.get("scopes")
            if not isinstance(raw_scopes, list):
                return False
            current_scopes = {str(s).lower() for s in raw_scopes}
            return required_scopes.issubset(current_scopes)
        except (aiohttp.ClientError, ValueError, RuntimeError):
            return False

    async def _trigger_device_flow_reauth(
        self, reason: str = "token invalidation"
    ) -> None:
        """Trigger device flow re-authentication when tokens are invalidated."""
        logging.info(
            f"🔄 Device flow re-authentication triggered for user={self.bot.username} due to {reason}. "
            "Please re-authorize the application with the required permissions to continue using the bot."
        )
        async with self._device_flow_lock:
            if self._device_flow_in_progress:
                return
            self._device_flow_in_progress = True
            # Pause background refresh during device flow
            if self.bot.token_manager:
                await self.bot.token_manager.pause_background_refresh(self.bot.username)
            try:
                if not self.bot.context.session:
                    logging.error(
                        f"❌ No session available for re-auth user={self.bot.username}"
                    )
                    return
                provisioner = TokenProvisioner(self.bot.context.session)
                try:
                    access, refresh, expiry = await provisioner._interactive_authorize(
                        self.bot.client_id, self.bot.client_secret, self.bot.username
                    )
                    if access and refresh:
                        # Update bot's tokens
                        self.bot.access_token = access
                        self.bot.refresh_token = refresh
                        self.bot.token_expiry = expiry
                        # Update token manager
                        if self.bot.token_manager is None:
                            logging.error(
                                f"❌ Token manager not available after re-auth user={self.bot.username}"
                            )
                            return
                        await self.bot.token_manager._upsert_token_info(
                            username=self.bot.username,
                            access_token=access,
                            refresh_token=refresh,
                            client_id=self.bot.client_id,
                            client_secret=self.bot.client_secret,
                            expiry=expiry,
                        )
                        logging.info(
                            f"✅ Device flow re-auth successful user={self.bot.username}"
                        )
                        # Persist changes
                        await self._persist_token_changes()
                        # Resume background refresh
                        if self.bot.token_manager:
                            await self.bot.token_manager.resume_background_refresh(
                                self.bot.username
                            )
                    else:
                        logging.error(
                            f"❌ Device flow re-auth failed user={self.bot.username}"
                        )
                except Exception as e:
                    logging.error(
                        f"💥 Device flow re-auth error user={self.bot.username}: {str(e)}"
                    )
            finally:
                self._device_flow_in_progress = False

    async def _persist_token_changes(self) -> None:
        """Persist updated token information to configuration."""
        if not self._validate_config_prerequisites():
            return
        user_config = self.bot._build_user_config()
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):
                return

    async def _persist_normalized_channels(self) -> None:
        """Persist normalized channel list to configuration."""
        config_file = getattr(self.bot, "config_file", None)
        if config_file is None:
            return
        user_config = self.bot._build_user_config()
        # Overwrite channels explicitly
        user_config["channels"] = self.bot.channels
        try:
            await queue_user_update(user_config, config_file)
        except (OSError, ValueError, RuntimeError) as e:
            logging.warning(f"Persist channels error: {str(e)}")

    def _validate_config_prerequisites(self) -> bool:
        """Validate that required config fields are present for persistence.

        Returns:
            True if all prerequisites are met.
        """
        if not getattr(self.bot, "config_file", None):
            logging.warning(
                f"📁 No config file specified cannot persist tokens user={self.bot.username}"
            )
            return False
        if not getattr(self.bot, "access_token", None):
            logging.warning(
                f"⚠️ Cannot save empty access token user={self.bot.username}"
            )
            return False
        if not getattr(self.bot, "refresh_token", None):
            logging.warning(
                f"⚠️ Cannot save empty refresh token user={self.bot.username}"
            )
            return False
        return True

    def _build_user_config(self) -> dict[str, Any]:
        """Build user configuration dict from current instance state.

        Returns:
            Dict containing all user configuration fields.
        """
        # Direct attribute access; mixin consumer guarantees these attributes.
        username = self.bot.username
        channels = self.bot.channels
        return {
            "username": username,
            "client_id": self.bot.client_id,
            "client_secret": self.bot.client_secret,
            "access_token": self.bot.access_token,
            "refresh_token": self.bot.refresh_token,
            "token_expiry": self.bot.token_expiry,
            "channels": channels,
            "is_prime_or_turbo": self.bot.use_random_colors,
            "enabled": getattr(self.bot, "enabled", True),
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
        config_file = self.bot.config_file
        if config_file is None:
            return False
        try:
            success = await async_update_user_in_config(user_config, config_file)
            if success:
                logging.debug(f"💾 Token changes saved user={self.bot.username}")
                return True
            # Fall through to generic handling below to trigger retries
            raise RuntimeError("update_user_in_config returned False")
        except FileNotFoundError:
            logging.error(
                f"📁 Config file not found path={self.bot.config_file} user={self.bot.username}"
            )
            return True
        except PermissionError:
            logging.error(
                f"🔒 Permission denied writing config user={self.bot.username}"
            )
            return True
        except (OSError, ValueError, RuntimeError) as e:
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
