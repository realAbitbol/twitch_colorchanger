"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import aiohttp

from .colors import BColors, generate_random_hex_color, get_different_twitch_color
from .config import disable_random_colors_for_user, update_user_in_config
from .error_handling import APIError, simple_retry
from .logger import logger
from .rate_limiter import get_rate_limiter
from .simple_irc import SimpleTwitchIRC
from .utils import print_log

# Constants
CHAT_COLOR_ENDPOINT = 'chat/color'


async def _make_api_request(method: str,
                            endpoint: str,
                            access_token: str,
                            client_id: str,
                            data: Dict[str,
                                       Any] = None,
                            params: Dict[str,
                                         Any] = None) -> Tuple[Dict[str,
                                                                    Any],
                                                               int,
                                                               Dict[str,
                                                                    str]]:
    """Make a simple HTTP request to Twitch API"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Client-Id': client_id,
        'Content-Type': 'application/json'
    }

    url = f'https://api.twitch.tv/helix/{endpoint}'

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=headers, json=data, params=params) as response:
            try:
                response_data = await response.json()
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                response_data = {}

            return response_data, response.status, dict(response.headers)


class TwitchColorBot:
    """Bot that changes Twitch username colors after each message"""

    OAUTH_PREFIX = 'oauth:'

    def __init__(
            self,
            token: str,
            refresh_token: str,
            client_id: str,
            client_secret: str,
            nick: str,
            channels: List[str],
            is_prime_or_turbo: bool = True,
            config_file: str = None,
            user_id: str = None):
        # User credentials
        self.username = nick
        self.access_token = token.replace(
            self.OAUTH_PREFIX,
            '') if token.startswith(
            self.OAUTH_PREFIX) else token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.token_expiry = None

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
        # Force a token refresh at launch (if refresh token available) to ensure
        # fresh 4h window
        await self._check_and_refresh_token(force=True)

        # Fetch user_id if not set
        if not self.user_id:
            user_info = await self._get_user_info()
            if user_info and 'id' in user_info:
                self.user_id = user_info['id']
                print_log(
                    f"✅ {
                        self.username}: Retrieved user_id: {
                        self.user_id}",
                    BColors.OKGREEN)
            else:
                print_log(
                    f"❌ {
                        self.username}: Failed to retrieve user_id",
                    BColors.FAIL)
                return

        # Get current color to avoid repeating it on first change
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            print_log(
                f"✅ {
                    self.username}: Initialized with current color: {current_color}",
                BColors.OKGREEN)

        # Create IRC connection
        self.irc = SimpleTwitchIRC()
        self.irc.connect(self.access_token, self.username, self.channels[0])

        # Join all configured channels
        for channel in self.channels:
            self.irc.join_channel(channel)

        # Set up message handler
        self.irc.set_message_handler(self.handle_irc_message)

        # Start background tasks
        self.token_task = asyncio.create_task(self._periodic_token_check())

        # Run IRC listening in executor since it's not async
        loop = asyncio.get_event_loop()
        self.irc_task = loop.run_in_executor(None, self.irc.listen)

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
                # Expected when cancelling task - log and re-raise for proper cleanup
                print_log("Token task cancelled during stop", BColors.OKBLUE, debug_only=True)
                raise

        # Disconnect IRC (this sets running=False on IRC object)
        if self.irc:
            self.irc.disconnect()

        # Wait for IRC task to finish (disconnect should cause it to exit)
        if self.irc_task and not self.irc_task.done():
            try:
                await asyncio.wait_for(self.irc_task, timeout=2.0)
            except asyncio.TimeoutError:
                print_log(
                    f"⚠️ IRC task didn't finish within timeout for {
                        self.username}", BColors.WARNING)
            except Exception as e:
                print_log(f"⚠️ Error waiting for IRC task: {e}", BColors.WARNING)

        # Add a small delay to ensure cleanup
        await asyncio.sleep(0.1)

    def handle_irc_message(self, sender: str, channel: str, message: str):
        """Handle IRC messages from SimpleTwitchIRC"""
        # Only react to our own messages
        if sender.lower() == self.username.lower():
            self.messages_sent += 1
            # Schedule color change in the event loop (no more fixed delays!)
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(self._change_color(), loop)
                # Don't wait for completion to avoid blocking the IRC thread
            except RuntimeError:
                # Fallback: run in new thread
                import threading
                threading.Thread(
                    target=lambda: asyncio.run(
                        self._change_color()),
                    daemon=True).start()

    def _handle_message(self, sender: str, message: str, channel: str):
        """Handle message (for testing compatibility)"""
        self.handle_irc_message(sender, channel, message)

    async def _periodic_token_check(self):
        """Periodically check and refresh token if needed"""
        while self.running:
            try:
                # Dynamic check interval based on token expiry
                check_interval = self._get_token_check_interval()
                await asyncio.sleep(check_interval)

                if self.running:  # Check if still running after sleep
                    await self._check_and_refresh_token()

            except asyncio.CancelledError:
                print_log(
                    '⏹️ Token check task cancelled',
                    BColors.WARNING,
                    debug_only=True)
                raise
            except Exception as e:
                print_log(
                    f'⚠️ Error in periodic token check for {
                        self.username}: {e}',
                    BColors.WARNING)
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)

    def _get_token_check_interval(self) -> int:
        """Get dynamic check interval based on token expiry time"""
        try:
            if self._has_token_expiry():
                hours_remaining = self._hours_until_expiry()
                if hours_remaining < 0.5:  # Less than 30 minutes
                    return 180  # Check every 3 minutes if <30 minutes remaining
                elif hours_remaining < 1:  # Less than 1 hour
                    return 300  # Check every 5 minutes if <1 hour remaining
                elif hours_remaining < 2:  # Less than 2 hours
                    return 600  # Check every 10 minutes if <2 hours remaining
                else:
                    return 1800  # Check every 30 minutes if >2 hours remaining
            else:
                return 600  # Default 10 minutes if no expiry known
        except Exception:
            return 600  # Default 10 minutes on error

    async def _check_and_refresh_token(self, force: bool = False):
        """Public coordinator for token validation / refresh.

        Args:
            force: Always attempt a refresh (when a refresh token exists) regardless of
                   current expiry / validation state. Used at startup.
        """
        if not self.refresh_token:
            print_log(
                f"⚠️ {
                    self.username}: No refresh token available",
                BColors.WARNING)
            return False

        if force:
            return await self._force_token_refresh(initial=True)

        # 1. If we have an expiry timestamp, handle via expiry logic.
        if self._has_token_expiry():
            return await self._check_expiring_token()

        # 2. Otherwise, validate via API (no known expiry stored).
        if await self._validate_token_via_api():
            return True

        # 3. Fallback refresh attempt when validation failed or not conclusive.
        return await self._attempt_standard_refresh()

    # --------------------- Helper methods (complexity reduction) --------------------- #
    def _has_token_expiry(self) -> bool:
        return bool(getattr(self, 'token_expiry', None))

    def _hours_until_expiry(self) -> float:
        if not self._has_token_expiry() or self.token_expiry is None:
            return float('inf')
        return (self.token_expiry - datetime.now()).total_seconds() / 3600

    async def _force_token_refresh(self, initial: bool = False) -> bool:
        label = "initial" if initial else "forced"
        print_log(f"🔄 {self.username}: Forcing {label} token refresh", BColors.OKBLUE)
        success = await self._refresh_access_token()
        if success:
            print_log(
                f"✅ {
                    self.username}: Forced token refresh succeeded",
                BColors.OKGREEN)
            self._persist_token_changes()
        else:
            print_log(f"❌ {self.username}: Forced token refresh failed", BColors.FAIL)
        return success

    async def _check_expiring_token(self) -> bool:
        hours_remaining = self._hours_until_expiry()
        print_log(
            f"🔑 {
                self.username}: Token expires in {
                hours_remaining:.1f} hours",
            debug_only=True)

        # Refresh when less than 1 hour remaining (for ~4 hour tokens)
        # This gives us plenty of buffer while not refreshing too early
        if hours_remaining < 1:
            if hours_remaining < 0.25:  # Less than 15 minutes
                print_log(
                    f"⏰ {
                        self.username}: Token expires in {
                        hours_remaining *
                        60:.0f} minutes, refreshing urgently...",
                    BColors.FAIL)
            else:
                print_log(
                    f"⏰ {
                        self.username}: Token expires in {
                        hours_remaining:.1f} hours, refreshing proactively...",
                    BColors.WARNING)
            return await self._attempt_standard_refresh()

        print_log(
            f"✅ {
                self.username}: Token is valid and has sufficient time remaining ({
                hours_remaining:.1f}h)",
            BColors.OKGREEN,
            debug_only=True)
        return True

    async def _validate_token_via_api(self) -> bool:
        try:
            user_info = await self._get_user_info()
            if user_info:
                print_log(
                    f"✅ {
                        self.username}: Token is valid (API check)",
                    BColors.OKGREEN,
                    debug_only=True)
                return True
            else:
                print_log(
                    f"🔍 {
                        self.username}: Token validation failed, attempting refresh...",
                    BColors.WARNING,
                    debug_only=True)
                return False
        except Exception as e:  # Broad by design; upstream already categorized.
            print_log(
                f"🔍 {
                    self.username}: Token validation failed ({e}), attempting refresh...",
                BColors.WARNING,
                debug_only=True)
            return False

    async def _attempt_standard_refresh(self) -> bool:
        success = await self._refresh_access_token()
        if success:
            print_log(
                f"✅ {
                    self.username}: Token refreshed and saved successfully",
                BColors.OKGREEN)
            self._persist_token_changes()
        else:
            print_log(f"❌ {self.username}: Token refresh failed", BColors.FAIL)
        return success

    async def _get_user_info(self):
        """Retrieve user information from Twitch API"""
        return await simple_retry(self._get_user_info_impl, user=self.username)

    async def _get_user_info_impl(self):
        """Implementation of user info retrieval"""
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed('get_user_info', is_user_request=True)

        try:
            data, status_code, headers = await _make_api_request(
                'GET', 'users', self.access_token, self.client_id
            )

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if status_code == 200 and data and data.get('data'):
                return data['data'][0]
            elif status_code == 429:
                self.rate_limiter.handle_429_error(headers, is_user_request=True)
                return None
            elif status_code == 401:
                # Don't log 401 as error - it's expected when tokens are expired
                # The calling function will handle the refresh
                return None
            else:
                logger.error(
                    f"Failed to get user info: {status_code}",
                    user=self.username,
                    status_code=status_code)
                return None

        except APIError as e:
            if e.status_code == 401:
                logger.warning("Token expired, attempting refresh", user=self.username)
                if await self._check_and_refresh_token():
                    # Retry with new token
                    return await self._get_user_info_impl()
                else:
                    raise APIError("Token refresh failed")
            raise
        except Exception as e:
            logger.error(
                f"Error getting user info: {e}",
                exc_info=True,
                user=self.username)
            return None

    async def _get_current_color(self):
        """Get the user's current color from Twitch API"""
        return await simple_retry(self._get_current_color_impl, user=self.username)

    async def _get_current_color_impl(self):
        """Implementation of current color retrieval"""
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed('get_current_color', is_user_request=True)

        try:
            params = {'user_id': self.user_id}
            data, status_code, headers = await _make_api_request(
                'GET', CHAT_COLOR_ENDPOINT, self.access_token, self.client_id, params=params
            )

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if status_code == 200 and data and data.get(
                    'data') and len(data['data']) > 0:
                color = data['data'][0].get('color')
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
        if hasattr(self, 'config_file') and self.config_file:
            user_config = {
                'username': self.username,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'channels': getattr(self, 'channels', [self.username.lower()]),
                'is_prime_or_turbo': self.use_random_colors  # Preserve the current setting
            }
            try:
                update_user_in_config(user_config, self.config_file)
                print_log(
                    f"💾 {
                        self.username}: Token changes saved to configuration",
                    BColors.OKGREEN)
            except Exception as e:
                print_log(
                    f"⚠️ {
                        self.username}: Failed to save token changes: {e}",
                    BColors.WARNING)

    async def _change_color(self, hex_color=None):
        """Change the username color via Twitch API"""
        # Wait for rate limiting before making request
        await self.rate_limiter.wait_if_needed('change_color', is_user_request=True)

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
                f"Error changing color: {e}",
                exc_info=True,
                user=self.username)
            return False

    def _select_color(self):
        """Select the appropriate color based on user settings"""
        if self.use_random_colors:
            # Use hex colors for Prime/Turbo users
            return generate_random_hex_color(exclude_color=self.last_color)
        else:
            # Use static Twitch preset colors for regular users
            return get_different_twitch_color(exclude_color=self.last_color)

    async def _attempt_color_change(self, color):
        """Attempt to change color and handle the response"""
        try:
            params = {'user_id': self.user_id, 'color': color}

            try:
                _, status_code, headers = await asyncio.wait_for(
                    _make_api_request(
                        'PUT', CHAT_COLOR_ENDPOINT, self.access_token, self.client_id, params=params
                    ),
                    timeout=10
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
            rate_status = self._get_rate_limit_display()
            logger.info(f"Color changed to {color}{rate_status}", user=self.username)
            return True
        elif status_code == 429:
            self.rate_limiter.handle_429_error(
                {}, is_user_request=True)  # headers were already processed
            logger.warning("Rate limited, will retry automatically", user=self.username)
            return False
        else:
            logger.error(
                f"Failed to change color. Status: {status_code}",
                user=self.username,
                status_code=status_code)
            return False

    def _handle_api_error(self, e):
        """Handle API errors, specifically the Turbo/Prime requirement error"""
        error_text = str(e)
        if ("Turbo or Prime user" in error_text or "Hex color code" in error_text) and self.use_random_colors:
            logger.warning(
                f"User {
                    self.username} requires Turbo/Prime for hex colors. Disabling random colors and using preset colors.",
                user=self.username)

            # Disable random colors for this user
            self.use_random_colors = False

            # Persist the change to config file
            if self.config_file:
                if disable_random_colors_for_user(self.username, self.config_file):
                    logger.info(
                        f"Disabled random colors for {
                            self.username} in configuration",
                        user=self.username)
                else:
                    logger.warning(
                        f"Failed to persist random color setting change for {
                            self.username}", user=self.username)

            return False  # Indicate that fallback is needed
        else:
            logger.error(
                f"Error changing color: {e}",
                exc_info=True,
                user=self.username)
            return False

    async def _try_preset_color_fallback(self):
        """Try changing color with preset colors as fallback"""
        try:
            color = get_different_twitch_color(exclude_color=self.last_color)
            params = {'user_id': self.user_id, 'color': color}

            _, status_code, headers = await asyncio.wait_for(
                _make_api_request(
                    'PUT', CHAT_COLOR_ENDPOINT, self.access_token, self.client_id, params=params
                ),
                timeout=10
            )

            # Update rate limiting info from response headers
            self.rate_limiter.update_from_headers(headers, is_user_request=True)

            if status_code == 204:
                self.colors_changed += 1
                self.last_color = color
                rate_status = self._get_rate_limit_display()
                logger.info(
                    f"Color changed to {color} (using preset colors){rate_status}",
                    user=self.username)
                return True
            else:
                logger.error(
                    f"Failed to change color with preset color. Status: {status_code}",
                    user=self.username,
                    status_code=status_code)
                return False

        except Exception as fallback_e:
            logger.error(
                f"Error changing color with preset color fallback: {fallback_e}",
                exc_info=True,
                user=self.username)
            return False

    def _get_rate_limit_display(self):
        """Get rate limit information for display in messages"""
        import time

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
        elif remaining > 10:
            # Getting low - show with time until reset
            return f" [{remaining}/{limit} reqs, reset in {reset_in:.0f}s]"
        else:
            # Very low - highlight the critical status
            return f" [⚠️ {remaining}/{limit} reqs, reset in {reset_in:.0f}s]"

    async def _refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        return await simple_retry(self._refresh_access_token_impl, user=self.username)

    async def _refresh_access_token_impl(self):
        """Implementation of token refresh"""
        token_data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post('https://id.twitch.tv/oauth2/token', data=token_data) as response:
                    if response.status == 200:
                        token_response = await response.json()
                        self.access_token = token_response['access_token']

                        # Update refresh token if provided
                        if 'refresh_token' in token_response:
                            self.refresh_token = token_response['refresh_token']

                        # Set token expiry if provided
                        if 'expires_in' in token_response:
                            self.token_expiry = datetime.now(
                            ) + timedelta(seconds=token_response['expires_in'])
                            logger.info(
                                f"Token will expire at {
                                    self.token_expiry.strftime('%Y-%m-%d %H:%M:%S')}",
                                user=self.username)

                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Token refresh failed. Status: {
                                response.status}, Response: {error_text}",
                            user=self.username,
                            status_code=response.status)
                return False

        except Exception as e:
            logger.error(
                f"Error refreshing token: {e}",
                exc_info=True,
                user=self.username)
            return False

    def close(self):
        """Close the bot and clean up resources"""
        print_log(
            f"🛑 Closing bot for {
                self.username}",
            BColors.WARNING,
            debug_only=False)
        self.running = False

        if self.irc:
            self.irc.disconnect()
            self.irc = None

    def print_statistics(self):
        """Print bot statistics"""
        print_log(
            f"📊 {
                self.username}: Messages sent: {
                self.messages_sent}, Colors changed: {
                self.colors_changed}")
