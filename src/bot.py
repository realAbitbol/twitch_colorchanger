"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from .async_irc import AsyncTwitchIRC
from .colors import BColors, generate_random_hex_color, get_different_twitch_color
from .config import disable_random_colors_for_user, update_user_in_config
from .error_handling import APIError, simple_retry
from .logger import logger
from .rate_limiter import get_rate_limiter
from .token_service import TokenService, TokenStatus
from .utils import print_log

# Constants
CHAT_COLOR_ENDPOINT = "chat/color"


async def _make_api_request(  # pylint: disable=too-many-arguments
    method: str,
    endpoint: str,
    access_token: str,
    client_id: str,
    data: Dict[str, Any] = None,
    params: Dict[str, Any] = None,
    session: "aiohttp.ClientSession" = None,
) -> Tuple[Dict[str, Any], int, Dict[str, str]]:
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
        channels: List[str],
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
        self.token_expiry: Optional[datetime] = None

        # HTTP session for API requests (required)
        if not http_session:
            raise ValueError(
                "http_session is required - bots must use shared HTTP session"
            )
        self.http_session = http_session

        # Token service for unified token management (required)
        self.token_service = TokenService(client_id, client_secret, http_session)

        # Bot settings
        self.channels = channels
        self.use_random_colors = is_prime_or_turbo
        self.config_file = config_file

        # IRC connection
        self.irc = None
        self.running = False

        # Background tasks
        self.token_task = None
        self.irc_task = None

        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0

        # Color tracking to avoid repeating the same color
        self.last_color = None

        # Rate limiter for API requests
        self.rate_limiter = get_rate_limiter(self.client_id, self.username)

    async def start(self):
        """Start the bot"""
        print_log(f"🚀 Starting bot for {self.username}", BColors.OKBLUE)
        self.running = True
        # Validate token and refresh only if needed
        print_log(f"🔍 {self.username}: Checking token validity...", BColors.OKCYAN)
        await self._check_and_refresh_token()

        # Fetch user_id if not set
        if not self.user_id:
            user_info = await self._get_user_info()
            if user_info and "id" in user_info:
                self.user_id = user_info["id"]
                print_log(
                    f"✅ {
                        self.username}: Retrieved user_id: {
                        self.user_id}",
                    BColors.OKGREEN,
                )
            else:
                print_log(
                    f"❌ {
                        self.username}: Failed to retrieve user_id",
                    BColors.FAIL,
                )
                return

        # Get current color to avoid repeating it on first change
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            print_log(
                f"✅ {
                    self.username}: Initialized with current color: {current_color}",
                BColors.OKGREEN,
            )

        # Create IRC connection using async IRC client
        print_log(f"🚀 {self.username}: Using async IRC client", BColors.OKCYAN)
        self.irc = AsyncTwitchIRC()

        # Deduplicate and normalize channels
        unique_channels = list(
            dict.fromkeys([ch.lower().replace("#", "") for ch in self.channels])
        )

        # Check if deduplication changed the channels list
        if unique_channels != self.channels:
            print_log(
                f"📝 {self.username}: Deduplicated channels: "
                f"{len(self.channels)} → {len(unique_channels)}",
                BColors.OKBLUE,
            )
            self.channels = (
                unique_channels  # Update bot's channel list with deduplicated channels
            )

            # Persist the deduplicated channels to configuration
            self._persist_channel_deduplication()
        else:
            self.channels = (
                unique_channels  # Update bot's channel list even if no change
            )

        # Set up all channels in IRC object before connecting
        self.irc.channels = unique_channels.copy()

        # Set up message handler BEFORE connecting to avoid race condition
        self.irc.set_message_handler(self.handle_irc_message)

        # Connect to IRC with the first channel (now async)
        if not await self.irc.connect(
            self.access_token, self.username, unique_channels[0]
        ):
            print_log(f"❌ {self.username}: Failed to connect to IRC", BColors.FAIL)
            return

        # Start IRC listening task immediately after connection
        print_log(
            f"👂 {self.username}: Starting async message listener...", BColors.OKCYAN
        )
        self.irc_task = asyncio.create_task(self.irc.listen())

        # Join all additional configured channels (now async)
        for channel in unique_channels[
            1:
        ]:  # Skip first channel, already joined in connect
            await self.irc.join_channel(channel)

        # Start token monitoring task
        self.token_task = asyncio.create_task(self._periodic_token_check())

        try:
            # Wait for either task to complete
            await asyncio.gather(self.token_task, self.irc_task, return_exceptions=True)
        except KeyboardInterrupt:
            print_log("🛑 Shutting down bot...", BColors.WARNING)
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot"""
        print_log(f"⏹️ Stopping bot for {self.username}", BColors.WARNING)
        self.running = False

        # Cancel background tasks
        if self.token_task and not self.token_task.done():
            self.token_task.cancel()
            try:
                await self.token_task
            except asyncio.CancelledError:
                # Expected when cancelling task
                print_log(
                    "Token task cancelled during stop", BColors.OKBLUE, debug_only=True
                )
                # Re-raise CancelledError as per asyncio best practices
                raise

        # Disconnect IRC (now async)
        if self.irc:
            try:
                await self.irc.disconnect()
            except Exception as e:
                print_log(f"⚠️ Error disconnecting IRC: {e}", BColors.WARNING)

        # Wait for IRC task to finish (disconnect should cause it to exit)
        if self.irc_task and not self.irc_task.done():
            try:
                await asyncio.wait_for(self.irc_task, timeout=2.0)
            except asyncio.TimeoutError:
                print_log(
                    f"⚠️ IRC task didn't finish within timeout for {
                        self.username}",
                    BColors.WARNING,
                )
                # Cancel the task if it's still running
                self.irc_task.cancel()
            except asyncio.CancelledError:
                # Expected if the task was cancelled
                # Re-raise CancelledError as per asyncio best practices
                raise
            except Exception as e:
                print_log(f"⚠️ Error waiting for IRC task: {e}", BColors.WARNING)

        # Ensure running flag is set to False (in case early return happened)
        self.running = False

        # Add a small delay to ensure cleanup
        await asyncio.sleep(0.1)

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

    async def _handle_message(self, sender: str, message: str, channel: str):
        """Handle message (for testing compatibility)"""
        await self.handle_irc_message(sender, channel, message)

    async def _periodic_token_check(self):
        """Periodically check and refresh token using adaptive scheduling"""
        last_irc_check = 0
        irc_check_interval = 120  # Check IRC health every 2 minutes

        while self.running:
            try:
                # Calculate sleep interval based on token service availability
                sleep_interval = self._calculate_check_interval(irc_check_interval)
                await asyncio.sleep(sleep_interval)

                current_time = time.time()
                if not self.running:  # Check if still running after sleep
                    break

                # Perform scheduled checks
                last_irc_check = await self._perform_scheduled_checks(
                    current_time, last_irc_check, irc_check_interval
                )

            except asyncio.CancelledError:
                print_log(
                    "⏹️ Token check task cancelled", BColors.WARNING, debug_only=True
                )
                raise
            except Exception as e:
                print_log(
                    f"⚠️ Error in periodic token check for {self.username}: {e}",
                    BColors.WARNING,
                )
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)

    def _calculate_check_interval(self, irc_check_interval: int) -> float:
        """Calculate the sleep interval for the next check"""
        if self.token_service and self.token_expiry:
            token_check_delay = self.token_service.next_check_delay(self.token_expiry)
            return min(irc_check_interval, token_check_delay)
        else:
            # Fallback to IRC interval if no token service or expiry
            return irc_check_interval

    async def _perform_scheduled_checks(
        self, current_time: float, last_irc_check: float, irc_check_interval: int
    ) -> float:
        """Perform IRC health and token checks as needed"""
        # Always check IRC health every 2 minutes
        if current_time - last_irc_check >= irc_check_interval:
            await self._check_irc_health()
            last_irc_check = current_time

        # Adaptive token checking
        if self.token_service and self.token_expiry:
            next_delay = self.token_service.next_check_delay(self.token_expiry)
            if next_delay <= 0:  # Time to check
                await self._check_and_refresh_token()
        else:
            # If no token service, check tokens every 10 minutes as fallback
            if current_time - last_irc_check >= 600:  # 10 minutes
                print_log(
                    f"⚠️ {self.username}: No TokenService available, "
                    "cannot perform adaptive token checks",
                    BColors.WARNING,
                )

        return last_irc_check

    async def _check_irc_health(self):
        """Check IRC connection health and reconnect if needed"""
        if not self.irc:
            return

        try:
            # Get connection health stats
            stats = self.irc.get_connection_stats()

            # Log health status in debug mode
            print_log(
                f"🏥 {self.username} IRC health: {stats['is_healthy']}, "
                f"activity: {stats['time_since_activity']:.1f}s ago, "
                f"connected: {stats['connected']}, running: {stats['running']}",
                BColors.OKBLUE,
                debug_only=True,
            )

            # Check if connection is unhealthy
            if not stats["is_healthy"]:
                print_log(
                    f"⚠️ {self.username}: IRC connection appears unhealthy - "
                    f"last activity {stats['time_since_activity']:.1f}s ago",
                    BColors.WARNING,
                )

                # Attempt to force reconnection
                await self._reconnect_irc()

        except Exception as e:
            print_log(
                f"⚠️ Error checking IRC health for {self.username}: {e}",
                BColors.WARNING,
            )

    async def _reconnect_irc(self):
        """Attempt to reconnect IRC connection"""
        try:
            print_log(
                f"🔄 {self.username}: Attempting IRC reconnection...", BColors.WARNING
            )

            # Cancel current IRC task if running
            if self.irc_task and not self.irc_task.done():
                self.irc_task.cancel()
                try:
                    await asyncio.wait_for(self.irc_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            # Force reconnection (await the coroutine!)
            success = await self.irc.force_reconnect()
            if success:
                # Restart IRC listening task (pure async)
                self.irc_task = asyncio.create_task(self.irc.listen())
                print_log(
                    f"✅ {self.username}: IRC reconnection successful", BColors.OKGREEN
                )
            else:
                print_log(f"❌ {self.username}: IRC reconnection failed", BColors.FAIL)

        except Exception as e:
            print_log(
                f"❌ Error reconnecting IRC for {self.username}: {e}", BColors.FAIL
            )

    async def _check_and_refresh_token(self, force: bool = False):
        """Check and refresh token using TokenService"""
        if not self.refresh_token:
            print_log(
                f"⚠️ {self.username}: No refresh token available",
                BColors.WARNING,
            )
            return False

        if not self.token_service:
            print_log(
                f"❌ {self.username}: TokenService not available "
                "(http_session required)",
                BColors.FAIL,
            )
            return False

        try:
            status, new_access_token, new_refresh_token, new_expiry = (
                await self.token_service.validate_and_refresh(
                    self.access_token,
                    self.refresh_token,
                    self.username,
                    self.token_expiry,
                    force,
                )
            )

            if status == TokenStatus.VALID:
                # Update expiry even for valid tokens
                if new_expiry:
                    self.token_expiry = new_expiry
                return True

            elif status == TokenStatus.REFRESHED:
                # Update all token information
                if new_access_token:
                    self.access_token = new_access_token
                if new_refresh_token:
                    self.refresh_token = new_refresh_token
                if new_expiry:
                    self.token_expiry = new_expiry

                # Persist changes to config file
                self._persist_token_changes()
                return True

            else:  # TokenStatus.FAILED
                return False

        except Exception as e:
            print_log(f"❌ {self.username}: Error in token service: {e}", BColors.FAIL)
            return False

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
            logger.error(
                f"Failed to get user info: {status_code}",
                user=self.username,
                status_code=status_code,
            )
            return None

        except APIError as e:
            if e.status_code == 401:
                logger.warning("Token expired, attempting refresh", user=self.username)
                if await self._check_and_refresh_token():
                    # Retry with new token
                    return await self._get_user_info_impl()
                raise APIError("Token refresh failed") from e
            raise
        except Exception as e:
            logger.error(
                f"Error getting user info: {e}", exc_info=True, user=self.username
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
                    logger.info(f"Current color is {color}", user=self.username)
                    return color
            elif status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            elif status_code == 401:
                # Token might be expired - let the exception handler deal with refresh
                return None

            # If no color set or API call fails, return None
            logger.info("No current color set (using default)", user=self.username)
            return None

        except Exception as e:
            logger.warning(f"Error getting current color: {e}", user=self.username)
            return None

    def _persist_token_changes(self):
        """Persist token changes to configuration file"""
        if hasattr(self, "config_file") and self.config_file:
            user_config = {
                "username": self.username,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "channels": getattr(self, "channels", [self.username.lower()]),
                # Preserve the current setting
                "is_prime_or_turbo": self.use_random_colors,
            }
            try:
                update_user_in_config(user_config, self.config_file)
                print_log(
                    f"💾 {self.username}: Token changes saved to configuration",
                    BColors.OKGREEN,
                )
            except Exception as e:
                print_log(
                    f"⚠️ {
                        self.username}: Failed to save token changes: {e}",
                    BColors.WARNING,
                )

    def _persist_channel_deduplication(self):
        """Persist deduplicated channels to configuration file"""
        if hasattr(self, "config_file") and self.config_file:
            user_config = {
                "username": self.username,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "channels": self.channels,  # Use the deduplicated channels
                "is_prime_or_turbo": self.use_random_colors,
            }
            try:
                update_user_in_config(user_config, self.config_file)
                print_log(
                    f"💾 {self.username}: Deduplicated channels saved to configuration",
                    BColors.OKGREEN,
                )
            except Exception as e:
                print_log(
                    f"⚠️ {self.username}: Failed to save deduplicated channels: {e}",
                    BColors.WARNING,
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
            logger.error(
                f"Error changing color: {e}", exc_info=True, user=self.username
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
            except asyncio.TimeoutError:
                logger.error("Failed to change color (timeout)", user=self.username)
                return False

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            return self._handle_color_change_response(status_code, color)

        except APIError as e:
            return self._handle_api_error(e)

    def _handle_color_change_response(self, status_code, color):
        """Handle the response from color change API call"""
        if status_code == 204:
            self.colors_changed += 1
            self.last_color = color  # Store the successfully applied color
            rate_status = self._get_rate_limit_display(debug_only=True)
            logger.info(f"Color changed to {color}{rate_status}", user=self.username)
            return True
        if status_code == 429:
            self.rate_limiter.handle_429_error(
                {}, is_user_request=True
            )  # headers were already processed
            logger.warning("Rate limited, will retry automatically", user=self.username)
            return False
        logger.error(
            f"Failed to change color. Status: {status_code}",
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
            logger.warning(
                f"User {self.username} requires Turbo/Prime for hex colors. "
                "Disabling random colors and using preset colors.",
                user=self.username,
            )

            # Disable random colors for this user
            self.use_random_colors = False

            # Persist the change to config file
            if self.config_file:
                if disable_random_colors_for_user(self.username, self.config_file):
                    logger.info(
                        f"Disabled random colors for {
                            self.username} in configuration",
                        user=self.username,
                    )
                else:
                    logger.warning(
                        f"Failed to persist random color setting change for {
                            self.username}",
                        user=self.username,
                    )

            return False  # Indicate that fallback is needed
        logger.error(f"Error changing color: {e}", exc_info=True, user=self.username)
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
                rate_status = self._get_rate_limit_display(debug_only=True)
                logger.info(
                    f"Color changed to {color} (using preset colors){rate_status}",
                    user=self.username,
                )
                return True
            logger.error(
                f"Failed to change color with preset color. Status: {status_code}",
                user=self.username,
                status_code=status_code,
            )
            return False

        except Exception as fallback_e:
            logger.error(
                f"Error changing color with preset color fallback: {fallback_e}",
                exc_info=True,
                user=self.username,
            )
            return False

    def _get_rate_limit_display(self, debug_only=False):
        """Get rate limit information for display in messages"""
        import os

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
        print_log(
            f"🛑 Closing bot for {
                self.username}",
            BColors.WARNING,
            debug_only=False,
        )
        self.running = False

        if self.irc:
            # For sync cleanup, we can't await, so just set the connection to None
            # The real cleanup happens in the async stop() method
            self.irc = None

    def print_statistics(self):
        """Print bot statistics"""
        print_log(
            f"📊 {
                self.username}: Messages sent: {
                self.messages_sent}, Colors changed: {
                self.colors_changed}"
        )
