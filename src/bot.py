"""Main bot class for Twitch color changing functionality"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import aiohttp

from .adaptive_scheduler import AdaptiveScheduler
from .application_context import ApplicationContext
from .async_irc import AsyncTwitchIRC
from .color_utils import get_random_hex, get_random_preset
from .config import update_user_in_config
from .logger import logger
from .retry_policies import COLOR_CHANGE_RETRY, DEFAULT_NETWORK_RETRY, run_with_retry
from .user_config_model import normalize_channels_list

# Constants
CHAT_COLOR_ENDPOINT = "chat/color"


async def _make_api_request(  # pylint: disable=too-many-arguments
    method: str,
    endpoint: str,
    access_token: str,
    client_id: str,
    data: dict[str, Any] = None,
    params: dict[str, Any] = None,
    session: aiohttp.ClientSession = None,
) -> tuple[dict[str, Any], int, dict[str, str]]:
    """Make a simple HTTP request to Twitch API using shared session"""
    if not session:
        raise ValueError(
            "HTTP session is required - no fallback to new session creation"
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": client_id,
        "Content-Type": "application/json",
    }

    url = f"https://api.twitch.tv/helix/{endpoint}"

    async with session.request(
        method, url, headers=headers, json=data, params=params
    ) as response:
        try:
            response_data = await response.json()
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            response_data = {}

        return response_data, response.status, dict(response.headers)


class TwitchColorBot:  # pylint: disable=too-many-instance-attributes
    """Bot that changes Twitch username colors after each message"""

    OAUTH_PREFIX = "oauth:"

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        context: ApplicationContext,
        token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        nick: str,
        channels: list[str],
        http_session: aiohttp.ClientSession,
        is_prime_or_turbo: bool = True,
        config_file: str = None,
        user_id: str = None,
    ):
        self.context = context

        # User credentials
        self.username = nick
        self.access_token = (
            token.replace(self.OAUTH_PREFIX, "")
            if token.startswith(self.OAUTH_PREFIX)
            else token
        )
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.token_expiry: datetime | None = None

        # HTTP session for API requests (required)
        if not http_session:
            raise ValueError(
                "http_session is required - bots must use shared HTTP session"
            )
        self.http_session = http_session

        # Token manager reference (assigned during start)
        self.token_manager = None  # Set during start()

        # Bot settings
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file

        # IRC connection and runtime flags
        self.irc = None
        self.running = False
        self.irc_task = None

        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0

        # Network health tracking
        self.last_successful_connection = time.time()
        self.connection_failure_start: float | None = None

        # Token failure tracking
        # Removed token failure tracking attributes (unused).  # noqa: ERA001

        # Color tracking
        self.last_color: str | None = None

        # Rate limiter via context
        self.rate_limiter = context.get_rate_limiter(self.client_id, self.username)

        # Adaptive scheduler (currently mostly idle, reserved for future tasks)
        self.scheduler = AdaptiveScheduler()

    async def start(self):
        """Start the bot"""
        logger.log_event("bot", "start", user=self.username)
        self.running = True
        # Register with centralized TokenManager
        logger.log_event("bot", "registering_token_manager", user=self.username)
        self.token_manager = self.context.token_manager
        self.token_manager.register_user(
            username=self.username,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=self.token_expiry,
        )
        # Token manager already started by context
        fresh = await self.token_manager.get_fresh_token(self.username)
        if fresh:
            self.access_token = fresh

        if not self.user_id:
            user_info = await self._get_user_info()
            if user_info and "id" in user_info:
                self.user_id = user_info["id"]
                logger.log_event(
                    "bot", "user_id_retrieved", user=self.username, user_id=self.user_id
                )
            else:
                logger.log_event(
                    "bot", "user_id_failed", level=logging.ERROR, user=self.username
                )
                return

        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            logger.log_event(
                "bot", "initialized_color", user=self.username, color=current_color
            )

        logger.log_event("bot", "using_async_irc", user=self.username)
        self.irc = AsyncTwitchIRC()

        normalized_channels, was_changed = normalize_channels_list(self.channels)
        if was_changed:
            logger.log_event(
                "bot",
                "normalized_channels",
                user=self.username,
                old_count=len(self.channels),
                new_count=len(normalized_channels),
            )
            self.channels = normalized_channels
            await self._persist_normalized_channels()
        else:
            self.channels = normalized_channels

        self.irc.channels = normalized_channels.copy()
        self.irc.set_message_handler(self.handle_irc_message)
        try:
            self.irc.set_auth_failure_callback(self._on_irc_auth_failure)  # type: ignore[attr-defined]
        except AttributeError:
            pass

        if not await self.irc.connect(
            self.access_token, self.username, normalized_channels[0]
        ):
            logger.log_event(
                "bot", "connect_failed", level=logging.ERROR, user=self.username
            )
            return

        logger.log_event("bot", "listener_start", user=self.username)
        self.irc_task = asyncio.create_task(self.irc.listen())

        for channel in normalized_channels[1:]:
            await self.irc.join_channel(channel)

        await self.scheduler.start()

        try:
            await self.irc_task
        except KeyboardInterrupt:
            logger.log_event(
                "bot", "shutdown_initiated", level=logging.WARNING, user=self.username
            )
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot"""
        logger.log_event("bot", "stopping", level=logging.WARNING, user=self.username)
        self.running = False

        # Stop scheduler
        await self.scheduler.stop()

        # Cancel background tasks (placeholder for future tasks)
        await self._cancel_token_task()

        # Disconnect IRC
        await self._disconnect_irc()

        # Wait for IRC task to finish
        await self._wait_for_irc_task()

        # Ensure running flag is set to False (in case early return happened)
        self.running = False

        # Small delay to let tasks finalize cleanly
        await asyncio.sleep(0.1)

    async def _cancel_token_task(self):
        """Cancel the token refresh background task (now handled by scheduler)"""
        # Token management is now handled by the adaptive scheduler
        # This method is kept for compatibility but does nothing
        pass

    async def _disconnect_irc(self):
        """Disconnect IRC connection"""
        if self.irc:
            try:
                await self.irc.disconnect()
            except Exception as e:
                logger.log_event(
                    "bot",
                    "disconnect_error",
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

    async def _wait_for_irc_task(self):
        """Wait for IRC task to finish with timeout"""
        if self.irc_task and not self.irc_task.done():
            try:
                await asyncio.wait_for(self.irc_task, timeout=2.0)
            except TimeoutError:
                logger.log_event(
                    "bot",
                    "waiting_irc_task_error",
                    level=logging.WARNING,
                    user=self.username,
                    error="timeout",
                )
                # Cancel the task if it's still running
                self.irc_task.cancel()
            except asyncio.CancelledError:
                # Expected if the task was cancelled
                # Re-raise CancelledError as per asyncio best practices
                raise
            except Exception as e:
                logger.log_event(
                    "bot",
                    "waiting_irc_task_error",
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

    async def handle_irc_message(self, sender: str, channel: str, message: str):
        """Handle IRC messages from the async IRC client"""
        # Suppress unused argument warnings
        _ = channel
        _ = message
        # Only react to our own messages
        if sender.lower() == self.username.lower():
            self.messages_sent += 1
            # Direct async color change - no more threading complexity!
            await self._change_color()

    # Removed _adaptive_token_check; token freshness handled on-demand by TokenManager

    ## Removed unused _check_scheduler_health (scheduler simplified)  # noqa: ERA001

    ## Removed unused get_failure_statistics (no external callers)  # noqa: ERA001

    ## Removed _update_network_status (unused).  # noqa: ERA001

    # --- Helper methods for network status (extracted to lower complexity) ---
    ## Removed _handle_connection_recovered (unused).  # noqa: ERA001

    ## Removed _record_or_get_failure_duration (unused).  # noqa: ERA001

    ## Removed _emit_failure_progress_events (unused).  # noqa: ERA001

    ## Removed unused _check_irc_health (IRC client owns health)  # noqa: ERA001

    ## Removed _check_and_refresh_token wrapper (unused).  # noqa: ERA001

    ## Removed deprecated token helper methods (centralized in TokenManager)  # noqa: ERA001

    async def _get_user_info(self):
        """Retrieve user information from Twitch API"""

        async def op():  # Wrap for retry policy
            return await self._get_user_info_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_user_info_impl(self):
        """Implementation of user info retrieval"""
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed("get_user_info", is_user_request=True)

        try:
            data, status_code, headers = await _make_api_request(
                "GET",
                "users",
                self.access_token,
                self.client_id,
                session=self.http_session,
            )

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if status_code == 200 and data and data.get("data"):
                return data["data"][0]
            if status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            if status_code == 401:
                # Don't log 401 as error - it's expected when tokens are expired
                # The calling function will handle the refresh
                return None
            logger.log_event(
                "bot",
                "user_info_failed_status",
                level=logging.ERROR,
                user=self.username,
                status_code=status_code,
            )
            return None

        except Exception as e:
            logger.log_event(
                "bot",
                "user_info_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return None

    async def _get_current_color(self):
        """Get the user's current color from Twitch API"""

        async def op() -> dict | None:
            return await self._get_current_color_impl()

        return await run_with_retry(op, DEFAULT_NETWORK_RETRY, user=self.username)

    async def _get_current_color_impl(self):
        """Implementation of current color retrieval"""
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed(
            "get_current_color", is_user_request=True
        )

        try:
            params = {"user_id": self.user_id}
            data, status_code, headers = await _make_api_request(
                "GET",
                CHAT_COLOR_ENDPOINT,
                self.access_token,
                self.client_id,
                params=params,
                session=self.http_session,
            )

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if (
                status_code == 200
                and data
                and data.get("data")
                and len(data["data"]) > 0
            ):
                color = data["data"][0].get("color")
                if color:
                    logger.log_event(
                        "bot", "current_color_is", user=self.username, color=color
                    )
                    return color
            elif status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            elif status_code == 401:
                # Token might be expired - let the exception handler deal with refresh
                return None

            # If no color set or API call fails, return None
            logger.log_event("bot", "no_current_color_set", user=self.username)
            return None

        except Exception as e:
            logger.log_event(
                "bot",
                "get_current_color_error",
                level=logging.WARNING,
                user=self.username,
                error=str(e),
            )
            return None

    async def _persist_token_changes(self):
        """Persist token changes to configuration file with atomic updates"""
        if not self._validate_config_prerequisites():
            return

        user_config = self._build_user_config()

        # Attempt to save with retries
        max_retries = 3
        for attempt in range(max_retries):
            if await self._attempt_config_save(user_config, attempt, max_retries):
                return  # Success

    def _validate_config_prerequisites(self) -> bool:
        """Validate prerequisites for config persistence"""
        if not hasattr(self, "config_file") or not self.config_file:
            logger.log_event(
                "bot",
                "no_config_file_for_persist",
                level=logging.WARNING,
                user=self.username,
            )
            return False

        if not self.access_token:
            logger.log_event(
                "bot", "empty_access_token", level=logging.WARNING, user=self.username
            )
            return False

        if not self.refresh_token:
            logger.log_event(
                "bot", "empty_refresh_token", level=logging.WARNING, user=self.username
            )
            return False

        return True

    async def _on_irc_auth_failure(self):
        """Callback invoked when IRC indicates authentication failure."""
        try:
            if not hasattr(self, "token_manager"):
                return
            refreshed = await self.token_manager.force_refresh(self.username)
            info = self.token_manager.get_token_info(self.username)
            if info and info.access_token:
                self.access_token = info.access_token
                if self.irc:
                    self.irc.update_token(info.access_token)
                if refreshed:
                    logger.log_event(
                        "bot", "irc_auth_refresh_success", user=self.username
                    )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "irc_auth_failure_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )

    def _build_user_config(self) -> dict:
        """Build user configuration dictionary"""
        return {
            "username": self.username,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "channels": getattr(self, "channels", [self.username.lower()]),
            "is_prime_or_turbo": self.use_random_colors,
        }

    async def _attempt_config_save(
        self, user_config: dict, attempt: int, max_retries: int
    ) -> bool:
        """Attempt to save config with error handling"""
        try:
            update_user_in_config(user_config, self.config_file)
            logger.log_event("bot", "token_saved", user=self.username)
            return True

        except FileNotFoundError:
            logger.log_event(
                "bot",
                "config_file_not_found",
                level=logging.ERROR,
                user=self.username,
                path=self.config_file,
            )
            return True  # Don't retry for missing file

        except PermissionError:
            logger.log_event(
                "bot",
                "config_permission_denied",
                level=logging.ERROR,
                user=self.username,
            )
            return True  # Don't retry for permission errors

        except Exception as e:
            return await self._handle_config_save_error(e, attempt, max_retries)

    async def _handle_config_save_error(
        self, error: Exception, attempt: int, max_retries: int
    ) -> bool:
        """Handle config save errors with retry logic"""
        if attempt < max_retries - 1:
            logger.log_event(
                "bot",
                "save_retry",
                level=logging.WARNING,
                user=self.username,
                attempt=attempt + 1,
                error=str(error),
            )
            # Brief delay before retry
            import asyncio

            await asyncio.sleep(0.1 * (attempt + 1))
            return False  # Continue retrying
        else:
            logger.log_event(
                "bot",
                "save_failed_final",
                level=logging.ERROR,
                user=self.username,
                attempts=max_retries,
                error=str(error),
            )
            return True  # Stop retrying

    async def _persist_normalized_channels(self):
        """Persist normalized channels to configuration file"""
        if hasattr(self, "config_file") and self.config_file:
            user_config = {
                "username": self.username,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "channels": self.channels,  # Use the normalized channels
                "is_prime_or_turbo": self.use_random_colors,
            }
            try:
                # Run potentially blocking file update in thread to avoid blocking loop
                import asyncio

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, update_user_in_config, user_config, self.config_file
                )
                logger.log_event("bot", "normalized_channels_saved", user=self.username)
            except Exception as e:
                logger.log_event(
                    "bot",
                    "normalized_channels_save_failed",
                    level=logging.WARNING,
                    user=self.username,
                    error=str(e),
                )

    async def _change_color(self, hex_color=None):
        """Change the username color via Twitch API"""
        # Determine target color
        color = hex_color if hex_color else self._select_color()

        async def op() -> bool:
            await self.rate_limiter.wait_if_needed("change_color", is_user_request=True)
            return await self._attempt_color_change(color)

        try:
            result = await run_with_retry(
                op, COLOR_CHANGE_RETRY, user=self.username, log_domain="retry"
            )
            if not result and self.use_random_colors and not hex_color:
                # fallback to preset if random hex failed
                preset_result = await self._try_preset_color_fallback()
                return preset_result
            return result
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "bot",
                "error_changing_color_internal",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return False

    def _select_color(self):
        """Select the appropriate color based on user settings"""
        if self.use_random_colors:
            # Use hex colors for Prime/Turbo users
            return get_random_hex(exclude=self.last_color)
        # Use static Twitch preset colors for regular users
        return get_random_preset(exclude=self.last_color)

    async def _attempt_color_change(self, color):
        """Attempt to change color and handle the response"""
        params = {"user_id": self.user_id, "color": color}

        # First attempt (with retry policy for transient errors)
        status_code = await self._perform_color_request(params, action="change_color")
        response = self._handle_color_change_response(status_code, color)
        if response != "token_refresh_needed":
            if status_code == 0:  # internal error sentinel
                logger.log_event(
                    "bot",
                    "color_change_internal_error",
                    level=logging.ERROR,
                    user=self.username,
                )
            return response

        # Refresh path
        logger.log_event("bot", "color_change_attempt_refresh", user=self.username)
        if not await self._check_and_refresh_token(force=True):
            logger.log_event(
                "bot", "color_refresh_failed", level=logging.ERROR, user=self.username
            )
            return False
        logger.log_event("bot", "color_retry_after_refresh", user=self.username)
        params_refreshed = {"user_id": self.user_id, "color": color}
        retry_status = await self._perform_color_request(
            params_refreshed, action="change_color"
        )
        retry_response = self._handle_color_change_response(retry_status, color)
        return False if retry_response == "token_refresh_needed" else retry_response

    def _handle_color_change_response(self, status_code, color):
        """Handle the response from color change API call"""
        if status_code == 204:
            self.colors_changed += 1
            self.last_color = color  # Store the successfully applied color
            logger.log_event("bot", "color_changed", user=self.username, color=color)
            return True
        if status_code == 429:
            self.rate_limiter.handle_429_error(
                {}, is_user_request=True
            )  # headers were already processed
            logger.log_event(
                "bot",
                "rate_limited_color_change",
                level=logging.WARNING,
                user=self.username,
            )
            return False
        if status_code == 401:
            # Token expired/invalid - trigger immediate refresh
            logger.log_event(
                "bot",
                "token_refresh_for_color",
                level=logging.WARNING,
                user=self.username,
            )
            return "token_refresh_needed"  # Special return value to trigger refresh
        logger.log_event(
            "bot",
            "color_change_status_failed",
            level=logging.ERROR,
            user=self.username,
            status_code=status_code,
        )
        return False

    ## Removed deprecated _handle_api_error placeholder  # noqa: ERA001

    async def _try_preset_color_fallback(self):
        """Try changing color with preset colors as fallback"""
        color = get_random_preset(exclude=self.last_color)
        params = {"user_id": self.user_id, "color": color}
        status_code = await self._perform_color_request(params, action="preset_color")
        if status_code == 204:
            self.colors_changed += 1
            self.last_color = color
            logger.log_event(
                "bot", "preset_color_changed", user=self.username, color=color
            )
            return True
        if status_code == 0:
            logger.log_event(
                "bot",
                "preset_color_internal_error",
                level=logging.ERROR,
                user=self.username,
            )
            return False
        if status_code == 401:
            logger.log_event(
                "bot", "preset_color_401", level=logging.WARNING, user=self.username
            )
            if await self._check_and_refresh_token(force=True):
                logger.log_event("bot", "preset_color_retry", user=self.username)
                # retry once after refresh
                retry_status = await self._perform_color_request(
                    params, action="preset_color"
                )
                if retry_status == 204:
                    self.colors_changed += 1
                    self.last_color = color
                    logger.log_event(
                        "bot",
                        "preset_color_changed",
                        user=self.username,
                        color=color,
                    )
                    return True
                logger.log_event(
                    "bot",
                    "preset_color_retry_failed_status",
                    level=logging.ERROR,
                    user=self.username,
                    status_code=retry_status,
                )
                return False
            logger.log_event(
                "bot",
                "preset_color_refresh_failed",
                level=logging.ERROR,
                user=self.username,
            )
            return False
        logger.log_event(
            "bot",
            "preset_color_failed_status",
            level=logging.ERROR,
            user=self.username,
            status_code=status_code,
        )
        return False

    async def _perform_color_request(self, params: dict, action: str) -> int:
        """Perform the color change HTTP PUT with retry and rate limiting.

        Returns status_code (int). Headers automatically update rate limiter.
        action distinguishes between change_color and preset_color for delay separation.
        """

        async def op() -> int:
            await self.rate_limiter.wait_if_needed(action, is_user_request=True)
            _, status_code, headers = await asyncio.wait_for(
                _make_api_request(
                    "PUT",
                    CHAT_COLOR_ENDPOINT,
                    self.access_token,
                    self.client_id,
                    params=params,
                    session=self.http_session,
                ),
                timeout=10,
            )
            self.rate_limiter.update_from_headers(headers, is_user_request=True)
            return status_code

        try:
            return await run_with_retry(
                op, COLOR_CHANGE_RETRY, user=self.username, log_domain="retry"
            )
        except TimeoutError:
            logger.log_event(
                "bot", "color_change_timeout", level=logging.ERROR, user=self.username
            )
            return 0  # distinguishable non-HTTP code
        except Exception as e:  # noqa: BLE001
            # Generic network/other error already logged via retry attempts; final log
            logger.log_event(
                "bot",
                "preset_color_error"
                if action == "preset_color"
                else "error_changing_color_internal",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return 0

    def _get_rate_limit_display(self, debug_only=False):
        """Get rate limit information for display in messages"""
        # Check if debug mode is enabled
        debug_enabled = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

        # If debug_only is True and debug is not enabled, return empty string
        if debug_only and not debug_enabled:
            return ""

        if not self.rate_limiter.user_bucket:
            return " [rate limit info pending]"

        bucket = self.rate_limiter.user_bucket
        current_time = time.time()

        # If bucket info is stale, indicate it
        if current_time - bucket.last_updated > 60:
            return " [rate limit info stale]"

        remaining = bucket.remaining
        limit = bucket.limit
        reset_in = max(0, bucket.reset_timestamp - current_time)

        # Format the rate limit info compactly
        if remaining > 100:
            # Plenty of requests left - show simple status
            return f" [{remaining}/{limit} reqs]"
        if remaining > 10:
            # Getting low - show with time until reset
            return f" [{remaining}/{limit} reqs, reset in {reset_in:.0f}s]"
        # Very low - highlight the critical status
        return f" [⚠️ {remaining}/{limit} reqs, reset in {reset_in:.0f}s]"

    def close(self):
        """Close the bot and clean up resources"""
        logger.log_event("bot", "closing_for_user", user=self.username)
        self.running = False

        # Note: Don't set self.irc = None here to avoid race conditions
        # with health checks. The real cleanup happens in the async stop() method

    def print_statistics(self):
        """Print bot statistics"""
        logger.log_event(
            "bot",
            "statistics",
            user=self.username,
            messages=self.messages_sent,
            colors=self.colors_changed,
        )
