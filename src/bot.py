"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import List

import aiohttp

from .colors import bcolors, generate_random_hex_color, get_different_twitch_color
from .utils import print_log
from .simple_irc import SimpleTwitchIRC
from .config import update_user_in_config


class TwitchColorBot:
    """Bot that changes Twitch username colors after each message"""
    
    OAUTH_PREFIX = 'oauth:'
    
    def __init__(self, token: str, refresh_token: str, client_id: str, client_secret: str, 
                 nick: str, channels: List[str], use_random_colors: bool = True, config_file: str = None,
                 user_id: str = None):
        # User credentials
        self.username = nick
        self.access_token = token.replace(self.OAUTH_PREFIX, '') if token.startswith(self.OAUTH_PREFIX) else token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.token_expiry = None
        
        # Bot settings
        self.channels = channels
        self.use_random_colors = use_random_colors
        self.config_file = config_file
        
        # IRC connection
        self.irc = None
        self.running = False
        
        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0
        
        # Color tracking to avoid repeating the same color
        self.last_color = None
    
    async def start(self):
        """Start the bot"""
        print_log(f"🚀 Starting bot for {self.username}", bcolors.OKBLUE)
        self.running = True
        
        # Check token validity first
        await self._check_and_refresh_token()
        
        # Fetch user_id if not set
        if not self.user_id:
            user_info = await self._get_user_info()
            if user_info and 'id' in user_info:
                self.user_id = user_info['id']
                print_log(f"✅ {self.username}: Retrieved user_id: {self.user_id}", bcolors.OKGREEN)
            else:
                print_log(f"❌ {self.username}: Failed to retrieve user_id", bcolors.FAIL)
                return
        
        # Get current color to avoid repeating it on first change
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            print_log(f"✅ {self.username}: Initialized with current color: {current_color}", bcolors.OKGREEN)
        
        # Create IRC connection
        self.irc = SimpleTwitchIRC()
        self.irc.connect(self.access_token, self.username, self.channels[0])
        
        # Join all configured channels
        for channel in self.channels:
            self.irc.join_channel(channel)
        
        # Set up message handler
        self.irc.set_message_handler(self.handle_irc_message)
        
        # Start background tasks
        token_task = asyncio.create_task(self._periodic_token_check())
        
        # Run IRC listening in executor since it's not async
        loop = asyncio.get_event_loop()
        irc_task = loop.run_in_executor(None, self.irc.listen)
        
        try:
            # Wait for either task to complete
            await asyncio.gather(token_task, irc_task, return_exceptions=True)
        except KeyboardInterrupt:
            print_log("🛑 Shutting down bot...", bcolors.WARNING)
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the bot"""
        print_log(f"⏹️ Stopping bot for {self.username}", bcolors.WARNING)
        self.running = False
        
        if self.irc:
            self.irc.disconnect()
        
        # Add a small delay to ensure cleanup
        await asyncio.sleep(0.1)
    
    def handle_irc_message(self, sender: str, channel: str, message: str):
        """Handle IRC messages from SimpleTwitchIRC"""
        # Only react to our own messages
        if sender.lower() == self.username.lower():
            self.messages_sent += 1
            # Schedule color change in the event loop
            try:
                loop = asyncio.get_event_loop()
                _ = asyncio.run_coroutine_threadsafe(self._delayed_color_change(), loop)
                # Don't wait for completion to avoid blocking the IRC thread
            except RuntimeError:
                # Fallback: run in new thread
                import threading
                threading.Thread(target=lambda: asyncio.run(self._delayed_color_change()), daemon=True).start()
    
    async def _delayed_color_change(self):
        """Delay color change by 1-3 seconds to avoid rate limiting"""
        await asyncio.sleep(random.uniform(1, 3))  # 1-3 second delay
        await self._change_color()
    
    async def _periodic_token_check(self):
        """Periodically check and refresh token if needed"""
        while self.running:
            try:
                # Check token every 10 minutes
                await asyncio.sleep(600)  # 10 minutes
                
                if self.running:  # Check if still running after sleep
                    await self._check_and_refresh_token()
                
            except asyncio.CancelledError:
                print_log('⏹️ Token check task cancelled', bcolors.WARNING, debug_only=True)
                raise
            except Exception as e:
                print_log(f'⚠️ Error in periodic token check for {self.username}: {e}', bcolors.WARNING)
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)
    
    async def _check_and_refresh_token(self):
        """Check token validity and refresh if needed"""
        if not self.refresh_token:
            print_log(f"⚠️ {self.username}: No refresh token available", bcolors.WARNING)
            return False
        
        try:
            # Check token expiry time if available
            if hasattr(self, 'token_expiry') and self.token_expiry:
                time_remaining = self.token_expiry - datetime.now()
                hours_remaining = time_remaining.total_seconds() / 3600
                
                # Always log time remaining in non-debug mode
                print_log(f"🔑 {self.username}: Token expires in {hours_remaining:.1f} hours")
                
                if hours_remaining < 1:
                    print_log(f"⏰ {self.username}: Token expires in less than 1 hour, refreshing...", bcolors.WARNING)
                    success = await self._refresh_access_token()
                    if success:
                        print_log(f"✅ {self.username}: Token refreshed and saved successfully", bcolors.OKGREEN)
                        self._persist_token_changes()
                    else:
                        print_log(f"❌ {self.username}: Token refresh failed", bcolors.FAIL)
                    return success
                else:
                    print_log(f"✅ {self.username}: Token is valid and has sufficient time remaining", bcolors.OKGREEN)
                    return True
            
            # Fallback: Check if current token is still valid via API
            user_info = await self._get_user_info()
            if user_info:
                print_log(f"✅ {self.username}: Token is still valid (API check)")
                return True
        except Exception as e:
            print_log(f"🔍 {self.username}: Token validation failed ({e}), attempting refresh...", bcolors.WARNING)
        
        # Try to refresh the token
        success = await self._refresh_access_token()
        if success:
            print_log(f"✅ {self.username}: Token refreshed and saved successfully", bcolors.OKGREEN)
            self._persist_token_changes()
        else:
            print_log(f"❌ {self.username}: Token refresh failed", bcolors.FAIL)
        
        return success
    
    async def _get_user_info(self):
        """Retrieve user information from Twitch API"""
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get('https://api.twitch.tv/helix/users', headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            return data['data'][0]
                    return None
        except Exception as e:
            print_log(f'⚠️ Error getting user info: {e}', bcolors.WARNING)
            return None
    
    async def _get_current_color(self):
        """Get the user's current color from Twitch API"""
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f'https://api.twitch.tv/helix/chat/color?user_id={self.user_id}'
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data') and len(data['data']) > 0:
                            color = data['data'][0].get('color')
                            if color:
                                print_log(f"🎨 {self.username}: Current color is {color}", bcolors.OKBLUE)
                                return color
                    # If no color set or API call fails, return None
                    print_log(f"🎨 {self.username}: No current color set (using default)", bcolors.OKBLUE)
                    return None
        except Exception as e:
            print_log(f'⚠️ Error getting current color: {e}', bcolors.WARNING)
            return None
    
    def _persist_token_changes(self):
        """Persist token changes to configuration file"""
        if hasattr(self, 'config_file') and self.config_file:
            user_config = {
                'username': self.username,
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'channels': getattr(self, 'channels', [self.username.lower()])
            }
            try:
                update_user_in_config(user_config, self.config_file)
                print_log(f"💾 {self.username}: Token changes saved to configuration", bcolors.OKGREEN)
            except Exception as e:
                print_log(f"⚠️ {self.username}: Failed to save token changes: {e}", bcolors.WARNING)
    
    async def _change_color(self):
        """Change the username color via Twitch API"""
        if self.use_random_colors:
            # Use hex colors for Prime/Turbo users
            color = generate_random_hex_color(exclude_color=self.last_color)
        else:
            # Use static Twitch preset colors for regular users
            color = get_different_twitch_color(exclude_color=self.last_color)
            
        print_log(f"🎨 {self.username}: Changing color to {color}", bcolors.OKBLUE)
        
        # URL encode the color for hex colors (# becomes %23)
        from urllib.parse import quote
        encoded_color = quote(color, safe='')
        
        url = f'https://api.twitch.tv/helix/chat/color?user_id={self.user_id}&color={encoded_color}'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, headers=headers) as response:
                    if response.status == 204:
                        self.colors_changed += 1
                        self.last_color = color  # Store the successfully applied color
                        print_log(f"✅ {self.username}: Color changed to {color}", bcolors.OKGREEN)
                    else:
                        error_text = await response.text()
                        print_log(f"❌ {self.username}: Failed to change color. Status: {response.status}, Response: {error_text}", bcolors.FAIL)
        except Exception as e:
            print_log(f"❌ {self.username}: Error changing color: {e}", bcolors.FAIL)

    async def _refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post('https://id.twitch.tv/oauth2/token', data=data) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        self.access_token = token_data['access_token']
                        
                        # Update refresh token if provided
                        if 'refresh_token' in token_data:
                            self.refresh_token = token_data['refresh_token']
                        
                        # Set token expiry if provided
                        if 'expires_in' in token_data:
                            self.token_expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
                            print_log(f"🔑 {self.username}: Token will expire at {self.token_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
                        
                        return True
                    else:
                        error_text = await response.text()
                        print_log(f"❌ {self.username}: Token refresh failed. Status: {response.status}, Response: {error_text}", bcolors.FAIL)
                    return False
        except Exception as e:
            print_log(f"❌ {self.username}: Error refreshing token: {e}", bcolors.FAIL)
            return False

    def close(self):
        """Close the bot and clean up resources"""
        print_log(f"🛑 Closing bot for {self.username}", bcolors.WARNING, debug_only=False)
        self.running = False
            
        if self.irc:
            self.irc.disconnect()
            self.irc = None

    def print_statistics(self):
        """Print bot statistics"""
        print_log(f"📊 {self.username}: Messages sent: {self.messages_sent}, Colors changed: {self.colors_changed}")

