"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import aiohttp

from .adaptive_scheduler import AdaptiveScheduler
from .async_irc import AsyncTwitchIRC
from .config import disable_random_colors_for_user, update_user_in_config
from .constants import NETWORK_PARTITION_THRESHOLD, PARTIAL_CONNECTIVITY_THRESHOLD
from .error_handling import APIError, simple_retry
from .logger import logger
from .rate_limiter import get_rate_limiter
from .token_manager import get_token_manager
from .user_config_model import normalize_channels_list


# Local color helpers (previously in colors.py)
def _twitch_preset_colors():
    return [
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
    ]


def get_different_twitch_color(exclude_color=None):
    colors = _twitch_preset_colors()
    if exclude_color is None or len(colors) <= 1:
        import random  # nosec B311

        return random.choice(colors)  # nosec B311
    available = [c for c in colors if c != exclude_color]
    import random  # nosec B311

    return random.choice(available)  # nosec B311


def generate_random_hex_color(exclude_color=None):
    import random  # nosec B311

    max_attempts = 10
    attempts = 0
    while attempts < max_attempts:
        hue = random.randint(0, 359)  # nosec B311
        saturation = random.randint(60, 100)  # nosec B311
        lightness = random.randint(35, 75)  # nosec B311
        c = (1 - abs(2 * lightness / 100 - 1)) * saturation / 100
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = lightness / 100 - c / 2
        if 0 <= hue < 60:
            r, g, b = c, x, 0
        elif 60 <= hue < 120:
            r, g, b = x, c, 0
        elif 120 <= hue < 180:
            r, g, b = 0, c, x
        elif 180 <= hue < 240:
            r, g, b = 0, x, c
        elif 240 <= hue < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x
        r = int((r + m) * 255)
        g = int((g + m) * 255)
        b = int((b + m) * 255)
        color = f"#{r:02x}{g:02x}{b:02x}"
        if exclude_color is None or color != exclude_color:
            return color
        attempts += 1
    return color


# print_log fully migrated to structured logger; legacy import removed

# Constants
CHAT_COLOR_ENDPOINT = "chat/color"


async def _make_api_request(  # pylint: disable=too-many-arguments
    method: str,
    endpoint: str,
    access_token: str,
    client_id: str,
    data: dict[str, Any] = None,
    params: dict[str, Any] = None,
    session: "aiohttp.ClientSession" = None,
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
        token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        nick: str,
        channels: list[str],
        http_session: "aiohttp.ClientSession",
        is_prime_or_turbo: bool = True,
        config_file: str = None,
        user_id: str = None,
    ):
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
        # Central token manager (singleton) initialized on start()
        self.token_manager = None  # Set during start()

        # Bot settings
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file

        # IRC connection
        self.irc = None
        self.running = False

        # Background tasks
        self.irc_task = None

        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0

        # Network partition detection / health tracking
        self.last_successful_connection = time.time()
        self.connection_failure_start: float | None = None

        # Token failure tracking
        self.token_failure_count = 0
        self.last_token_failure: float | None = None
        self.consecutive_refresh_failures = 0

        # Color tracking to avoid repeating the same color
        self.last_color: str | None = None

        # Rate limiter for API requests
        self.rate_limiter = get_rate_limiter(self.client_id, self.username)

        # Adaptive scheduler (currently mostly idle, reserved for future tasks)
        self.scheduler = AdaptiveScheduler()

    async def start(self):
        """Start the bot"""
        logger.log_event("bot", "start", user=self.username)
        self.running = True
        # Register with centralized TokenManager
        logger.log_event("bot", "registering_token_manager", user=self.username)
        self.token_manager = get_token_manager(self.http_session)
        self.token_manager.register_user(
            username=self.username,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=self.token_expiry,
        )
        await self.token_manager.start()
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
            self._persist_normalized_channels()
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

    async def _check_scheduler_health(self):
        """Monitor scheduler health and restart if necessary"""
        try:
            health = self.scheduler.get_health_status()

            if not health["running"]:
                logger.log_event(
                    "bot",
                    "scheduler_not_running",
                    level=logging.ERROR,
                    user=self.username,
                )
                await self.scheduler.start()
                return

            if not health["has_scheduler_task"]:
                logger.log_event(
                    "bot",
                    "scheduler_task_stopped",
                    level=logging.ERROR,
                    user=self.username,
                )
                await self.scheduler.stop()
                await self.scheduler.start()
                return

            # Check if scheduler is stalled (next task delay is unreasonably high)
            next_delay = health["next_task_delay"]
            if next_delay > 3600:  # More than 1 hour
                logger.log_event(
                    "bot",
                    "scheduler_stalled",
                    level=logging.WARNING,
                    user=self.username,
                    next_delay=next_delay,
                )

        except Exception as e:
            logger.log_event(
                "bot",
                "scheduler_check_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )

    def get_failure_statistics(self) -> dict:
        """Get token failure statistics for monitoring"""
        return {
            "total_token_failures": self.token_failure_count,
            "consecutive_refresh_failures": self.consecutive_refresh_failures,
            "last_token_failure": self.last_token_failure,
            "time_since_last_failure": (
                time.time() - self.last_token_failure
                if self.last_token_failure
                else None
            ),
            "is_in_failure_state": self.consecutive_refresh_failures >= 3,
        }

    def _update_network_status(self, stats: dict[str, Any]) -> None:
        """Update network partition detection status (reduced complexity)."""
        current_time = time.time()

        # Fast path: healthy connection
        if stats.get("connected") and stats.get("is_healthy"):
            self._handle_connection_recovered(current_time)
            return

        # Unhealthy path
        failure_duration = self._record_or_get_failure_duration(current_time)
        self._emit_failure_progress_events(failure_duration)

    # --- Helper methods for network status (extracted to lower complexity) ---
    def _handle_connection_recovered(self, current_time: float) -> None:
        if self.connection_failure_start is None:
            # Nothing to recover
            self.last_successful_connection = current_time
            return
        failure_duration = current_time - self.connection_failure_start
        self.last_successful_connection = current_time
        if failure_duration > PARTIAL_CONNECTIVITY_THRESHOLD:
            logger.log_event(
                "bot",
                "connection_recovered",
                user=self.username,
                duration=failure_duration,
            )
        self.connection_failure_start = None

    def _record_or_get_failure_duration(self, current_time: float) -> float:
        if self.connection_failure_start is None:
            self.connection_failure_start = current_time
            logger.log_event(
                "bot",
                "connection_failure_detected",
                level=logging.WARNING,
                user=self.username,
            )
            return 0.0
        return current_time - self.connection_failure_start

    def _emit_failure_progress_events(self, failure_duration: float) -> None:
        if failure_duration > PARTIAL_CONNECTIVITY_THRESHOLD:
            logger.log_event(
                "bot",
                "partial_connectivity",
                level=logging.WARNING,
                user=self.username,
                duration=failure_duration,
            )
        if failure_duration > NETWORK_PARTITION_THRESHOLD:
            logger.log_event(
                "bot",
                "network_partition",
                level=logging.ERROR,
                user=self.username,
                duration=failure_duration,
            )

    def _check_irc_health(self):
        """Check IRC connection health - reconnection is handled by IRC level"""
        if not self.irc:
            return

        try:
            # Get structured health snapshot (contains all needed data)
            health_data = self.irc.get_health_snapshot()

            # Create minimal stats object for network status compatibility
            stats_compat = {
                "time_since_activity": health_data.get("time_since_activity", 0.0)
                or 0.0,
                "is_healthy": health_data.get("healthy", False),
                "connected": health_data.get("connected", False),
                "running": health_data.get("running", False),
            }

            # Update network partition detection status
            self._update_network_status(stats_compat)

            # Log health status with detailed reasons
            if health_data["healthy"]:
                activity_time = health_data.get("time_since_activity") or 0.0
                logger.log_event(
                    "bot",
                    "irc_health_ok",
                    user=self.username,
                    state=health_data.get("state"),
                    activity_time=activity_time,
                )
            else:
                # Show unhealthy reasons
                reasons_str = ", ".join(health_data["reasons"])
                logger.log_event(
                    "bot",
                    "irc_unhealthy",
                    level=logging.WARNING,
                    user=self.username,
                    reasons=reasons_str,
                    state=health_data.get("state"),
                )

                # Inform that IRC will handle reconnection
                logger.log_event(
                    "bot",
                    "irc_reconnect_auto",
                    user=self.username,
                )

        except Exception as e:
            logger.log_event(
                "bot",
                "irc_health_check_error",
                level=logging.WARNING,
                user=self.username,
                error=str(e),
            )

    async def _check_and_refresh_token(
        self, force: bool = False
    ):  # Backwards compatibility wrapper
        if not hasattr(self, "token_manager"):
            return False
        if not self.token_manager:
            return False
        if force:
            await self.token_manager.force_refresh(self.username)
        fresh = await self.token_manager.get_fresh_token(self.username)
        if fresh:
            self.access_token = fresh
            return True
        return False

    def _validate_token_prerequisites(self) -> bool:
        return True  # TokenManager handles validation logic centrally

    def _handle_token_status(self):  # Deprecated path
        return True

    def _handle_valid_token(self):  # Deprecated
        return True

    def _handle_refreshed_token(self):  # Deprecated
        return True

    def _handle_failed_token(self):  # Deprecated
        return False

    def _display_token_expiry(self):
        """Display token expiry information"""
        if not self.token_expiry:
            return

        time_remaining = self.token_expiry - datetime.now()

        if time_remaining.total_seconds() <= 0:
            logger.log_event(
                "bot", "token_expired", level=logging.WARNING, user=self.username
            )
        else:
            # Convert to hours and minutes for display
            total_seconds = int(time_remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            if hours > 0:
                time_str = f"{hours}h {minutes}m"
            else:
                time_str = f"{minutes}m"

            logger.log_event(
                "bot", "token_expires_in", user=self.username, time_str=time_str
            )

    async def _get_user_info(self):
        """Retrieve user information from Twitch API"""
        return await simple_retry(self._get_user_info_impl, user=self.username)

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

        except APIError as e:
            if e.status_code == 401:
                logger.log_event(
                    "bot",
                    "user_info_token_expired",
                    level=logging.WARNING,
                    user=self.username,
                )
                if await self._check_and_refresh_token():
                    # Retry with new token
                    return await self._get_user_info_impl()
                raise APIError("Token refresh failed") from e
            raise
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
        return await simple_retry(self._get_current_color_impl, user=self.username)

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

    def _persist_token_changes(self):
        """Persist token changes to configuration file with atomic updates"""
        if not self._validate_config_prerequisites():
            return

        user_config = self._build_user_config()

        # Attempt to save with retries
        max_retries = 3
        for attempt in range(max_retries):
            if self._attempt_config_save(user_config, attempt, max_retries):
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

    def _attempt_config_save(
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
            return self._handle_config_save_error(e, attempt, max_retries)

    def _handle_config_save_error(
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
            import time

            time.sleep(0.1 * (attempt + 1))
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

    def _persist_normalized_channels(self):
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
                update_user_in_config(user_config, self.config_file)
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
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed("change_color", is_user_request=True)

        if hex_color:
            # Use the provided hex color
            color = hex_color
        else:
            # Select color based on user settings
            color = self._select_color()

        try:
            success = await self._attempt_color_change(color)
            if not success and self.use_random_colors and not hex_color:
                # Try fallback to preset colors if random colors failed due to
                # Turbo/Prime requirement
                success = await self._try_preset_color_fallback()
            return success
        except Exception as e:
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
            return generate_random_hex_color(exclude_color=self.last_color)
        # Use static Twitch preset colors for regular users
        return get_different_twitch_color(exclude_color=self.last_color)

    async def _attempt_color_change(self, color):
        """Attempt to change color and handle the response"""
        try:
            params = {"user_id": self.user_id, "color": color}

            try:
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
            except TimeoutError:
                logger.log_event(
                    "bot",
                    "color_change_timeout",
                    level=logging.ERROR,
                    user=self.username,
                )
                return False

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            response = self._handle_color_change_response(status_code, color)

            # Handle token refresh case
            if response == "token_refresh_needed":
                logger.log_event(
                    "bot", "color_change_attempt_refresh", user=self.username
                )

                # Try to refresh token
                refresh_success = await self._check_and_refresh_token(force=True)
                if refresh_success:
                    logger.log_event(
                        "bot", "color_retry_after_refresh", user=self.username
                    )

                    # Retry the color change with new token
                    try:
                        _, retry_status_code, retry_headers = await asyncio.wait_for(
                            _make_api_request(
                                "PUT",
                                CHAT_COLOR_ENDPOINT,
                                self.access_token,  # Now using refreshed token
                                self.client_id,
                                params=params,
                                session=self.http_session,
                            ),
                            timeout=10,
                        )

                        # Update rate limiting info from retry headers
                        self.rate_limiter.update_from_headers(
                            retry_headers, is_user_request=True
                        )

                        # Handle the retry response (but don't trigger another refresh)
                        retry_response = self._handle_color_change_response(
                            retry_status_code, color
                        )
                        return (
                            retry_response
                            if retry_response != "token_refresh_needed"
                            else False
                        )

                    except Exception:
                        logger.log_event(
                            "bot",
                            "color_change_status_failed",
                            level=logging.ERROR,
                            user=self.username,
                            status_code="retry_error",
                        )
                        return False
                else:
                    logger.log_event(
                        "bot",
                        "color_refresh_failed",
                        level=logging.ERROR,
                        user=self.username,
                    )
                    return False

            return response

        except APIError as e:
            return self._handle_api_error(e)

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

    def _handle_api_error(self, e):
        """Handle API errors, specifically the Turbo/Prime requirement error"""
        error_text = str(e)
        if (
            "Turbo or Prime user" in error_text or "Hex color code" in error_text
        ) and self.use_random_colors:
            logger.log_event(
                "bot",
                "turbo_required_disabling_random",
                level=logging.WARNING,
                user=self.username,
            )

            # Disable random colors for this user
            self.use_random_colors = False

            # Persist the change to config file
            if self.config_file:
                if disable_random_colors_for_user(self.username, self.config_file):
                    logger.log_event(
                        "bot", "random_colors_disabled_persisted", user=self.username
                    )
                else:
                    logger.log_event(
                        "bot",
                        "random_colors_persist_failed",
                        level=logging.WARNING,
                        user=self.username,
                    )

            return False  # Indicate that fallback is needed
        logger.log_event(
            "bot",
            "error_changing_color_internal",
            level=logging.ERROR,
            user=self.username,
            error=str(e),
        )
        return False

    async def _try_preset_color_fallback(self):
        """Try changing color with preset colors as fallback"""
        try:
            color = get_different_twitch_color(exclude_color=self.last_color)
            params = {"user_id": self.user_id, "color": color}

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

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if status_code == 204:
                self.colors_changed += 1
                self.last_color = color
                logger.log_event(
                    "bot", "preset_color_changed", user=self.username, color=color
                )
                return True
            elif status_code == 401:
                # Token expired/invalid - try to refresh and retry
                logger.log_event(
                    "bot", "preset_color_401", level=logging.WARNING, user=self.username
                )

                refresh_success = await self._check_and_refresh_token(force=True)
                if refresh_success:
                    logger.log_event("bot", "preset_color_retry", user=self.username)

                    # Retry with refreshed token
                    try:
                        _, retry_status_code, retry_headers = await asyncio.wait_for(
                            _make_api_request(
                                "PUT",
                                CHAT_COLOR_ENDPOINT,
                                self.access_token,  # Now using refreshed token
                                self.client_id,
                                params=params,
                                session=self.http_session,
                            ),
                            timeout=10,
                        )

                        self.rate_limiter.update_from_headers(
                            retry_headers, is_user_request=True
                        )

                        if retry_status_code == 204:
                            self.colors_changed += 1
                            self.last_color = color
                            self._get_rate_limit_display(debug_only=True)
                            logger.log_event(
                                "bot",
                                "preset_color_changed",
                                user=self.username,
                                color=color,
                            )
                            return True
                        else:
                            logger.log_event(
                                "bot",
                                "preset_color_retry_failed_status",
                                level=logging.ERROR,
                                user=self.username,
                                status_code=retry_status_code,
                            )
                            return False

                    except Exception as retry_e:
                        logger.log_event(
                            "bot",
                            "preset_color_retry_error",
                            level=logging.ERROR,
                            user=self.username,
                            error=str(retry_e),
                        )
                        return False
                else:
                    logger.log_event(
                        "bot",
                        "preset_color_refresh_failed",
                        level=logging.ERROR,
                        user=self.username,
                    )
                    return False
            else:
                logger.log_event(
                    "bot",
                    "preset_color_failed_status",
                    level=logging.ERROR,
                    user=self.username,
                    status_code=status_code,
                )
                return False

        except Exception as fallback_e:
            logger.log_event(
                "bot",
                "preset_color_error",
                level=logging.ERROR,
                user=self.username,
                error=str(fallback_e),
            )
            return False

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
