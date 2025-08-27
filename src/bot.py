"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp

from .colors import bcolors, generate_random_hex_color, get_twitch_colors
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
        self.session = None
        
        # IRC connection
        self.irc = None
        self.running = False
        
        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0
    
    async def start(self):
        """Start the bot"""
        print_log(f"🚀 Starting bot for {self.username}", bcolors.OKBLUE)
        self.running = True
        
        # Check token validity first
        await self.check_and_refresh_token()
        
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
            await self.irc.disconnect()
        
        if self.session:
            await self.session.close()
    
    def handle_irc_message(self, sender: str, channel: str, message: str):
        """Handle IRC messages from SimpleTwitchIRC"""
        # Display all user messages with username and channel
        print_log(f"💬 {sender} in #{channel}: {message[:100]}{'...' if len(message) > 100 else ''}")
        
        # Only react to our own messages
        if sender.lower() == self.username.lower():
            self.messages_sent += 1
            print_log("🎯 My message detected - triggering color change", bcolors.OKGREEN)
            # Schedule color change in the event loop
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(self.delayed_color_change(), loop)
            except RuntimeError:
                # Fallback: run in new thread
                import threading
                threading.Thread(target=lambda: asyncio.run(self.change_color()), daemon=True).start()
    
    async def delayed_color_change(self):
        """Change color after a short delay"""
        await asyncio.sleep(random.uniform(1, 3))  # 1-3 second delay
        await self.change_color()
    
    async def _periodic_token_check(self):
        """Periodically check and refresh token if needed"""
        while self.running:
            try:
                # Check token every 10 minutes
                await asyncio.sleep(600)  # 10 minutes
                
                if self.running:  # Check if still running after sleep
                    await self.check_and_refresh_token()
                
            except asyncio.CancelledError:
                print_log('⏹️ Token check task cancelled', bcolors.WARNING, debug_only=True)
                raise
            except Exception as e:
                print_log(f'⚠️ Error in periodic token check for {self.username}: {e}', bcolors.WARNING)
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)
    
    async def check_and_refresh_token(self):
        """Check if token needs refreshing and refresh if necessary"""
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
                    success = await self.refresh_access_token()
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
            user_info = await self.get_user_info()
            if user_info:
                print_log(f"✅ {self.username}: Token is still valid (API check)")
                return True
        except Exception as e:
            print_log(f"🔍 {self.username}: Token validation failed ({e}), attempting refresh...", bcolors.WARNING)
        
        # Try to refresh the token
        success = await self.refresh_access_token()
        if success:
            print_log(f"✅ {self.username}: Token refreshed and saved successfully", bcolors.OKGREEN)
            self._persist_token_changes()
        else:
            print_log(f"❌ {self.username}: Token refresh failed", bcolors.FAIL)
        
        return success
    
    async def get_user_info(self):
        """Get user information from Twitch API"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            async with self.session.get('https://api.twitch.tv/helix/users', headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data'):
                        return data['data'][0]
                return None
        except Exception as e:
            print_log(f'⚠️ Error getting user info: {e}', bcolors.WARNING)
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
    
    async def change_color(self):
        """Change the username color via Twitch API"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        if self.use_random_colors:
            # Use hex colors for Prime/Turbo users
            color = generate_random_hex_color()
        else:
            # Use static Twitch preset colors for regular users
            twitch_colors = get_twitch_colors()
            color = random.choice(twitch_colors)
            
        print_log(f"🎨 {self.username}: Changing color to {color}", bcolors.OKBLUE)
        
        url = f'https://api.twitch.tv/helix/chat/color?user_id={self.user_id}&color={color}'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            async with self.session.put(url, headers=headers) as response:
                if response.status == 204:
                    self.colors_changed += 1
                    print_log(f"✅ {self.username}: Color changed to {color}", bcolors.OKGREEN)
                else:
                    error_text = await response.text()
                    print_log(f"❌ {self.username}: Failed to change color. Status: {response.status}, Response: {error_text}", bcolors.FAIL)
        except Exception as e:
            print_log(f"❌ {self.username}: Error changing color: {e}", bcolors.FAIL)
    
    async def set_username_color(self, color: str):
        """Set username color to a specific color"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        # Ensure color starts with #
        if not color.startswith('#'):
            color = f'#{color}'
        
        print_log(f"🎨 {self.username}: Setting color to {color}", bcolors.OKBLUE)
        
        url = f'https://api.twitch.tv/helix/chat/color?user_id={self.user_id}&color={color.replace("#", "%23")}'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            async with self.session.put(url, headers=headers) as response:
                if response.status == 204:
                    print_log(f"✅ {self.username}: Color set to {color}", bcolors.OKGREEN)
                    return True
                else:
                    error_text = await response.text()
                    print_log(f"❌ {self.username}: Failed to set color. Status: {response.status}, Response: {error_text}", bcolors.FAIL)
                    return False
        except Exception as e:
            print_log(f"❌ {self.username}: Error setting color: {e}", bcolors.FAIL)
            return False
    
    async def refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            async with self.session.post('https://id.twitch.tv/oauth2/token', data=data) as response:
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

    async def close(self):
        """Close the bot and clean up resources"""
        print_log(f"🛑 Closing bot for {self.username}", bcolors.WARNING, debug_only=False)
        self.running = False
        
        if self.session:
            await self.session.close()
            self.session = None
            
        if self.irc:
            self.irc.disconnect()
            self.irc = None

    def print_statistics(self):
        """Print bot statistics"""
        print_log(f"📊 {self.username}: Messages sent: {self.messages_sent}, Colors changed: {self.colors_changed}")

