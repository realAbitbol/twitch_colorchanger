"""
Main bot class for Twitch color changing functionality
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp

from .colors import bcolors
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
        
        # Available colors for random selection
        self.colors = [
            '#FF0000', '#0000FF', '#00FF00', '#FFFF00', '#FF7F50',
            '#9ACD32', '#FF4500', '#2E8B57', '#DAA520', '#D2691E',
            '#5F9EA0', '#1E90FF', '#FF69B4', '#8A2BE2', '#00FF7F'
        ]
    
    async def start(self):
        """Start the bot"""
        print_log(f"🚀 Starting bot for {self.username}", bcolors.OKBLUE)
        self.running = True
        
        # Check token validity first
        await self.check_and_refresh_token()
        
        # Create IRC connection
        self.irc = SimpleTwitchIRC()
        await self.irc.connect(self.access_token, self.username, self.channels[0])
        
        # Set up message handler
        self.irc.set_message_handler(self.handle_irc_message)
        
        # Start background tasks
        token_task = asyncio.create_task(self._periodic_token_check())
        irc_task = asyncio.create_task(self.irc.listen())
        
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
        
        color = random.choice(self.colors) if self.use_random_colors else self.colors[0]
        print_log(f"🎨 {self.username}: Changing color to {color}", bcolors.OKBLUE)
        
        url = f'https://api.twitch.tv/helix/chat/color?user_id={self.user_id}&color={color.replace("#", "%23")}'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            async with self.session.put(url, headers=headers) as response:
                if response.status == 204:
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

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp
from twitchio.ext import commands

from .colors import bcolors
from .utils import print_log


class TwitchColorBot(commands.Bot):
    """Bot that changes Twitch username colors after each message"""
    
    def __init__(self, token: str, refresh_token: str, client_id: str, client_secret: str, 
                 nick: str, channels: List[str], use_random_colors: bool = True, config_file: str = None):
        super().__init__(
            token=token,
            prefix='!',
            initial_channels=channels,
            nick=nick
        )
        
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.channels = channels
        self.use_random_colors = use_random_colors
        self.token_expiry = None
        self.session = None
        self.config_file = config_file
        
        # Color management
        self.last_color = None
        self.color_history = []
        self.max_history = 5
        
        # Predefined Twitch colors
        self.preset_colors = [
            'Blue', 'BlueViolet', 'CadetBlue', 'Chocolate', 'Coral', 'DodgerBlue',
            'Firebrick', 'GoldenRod', 'Green', 'HotPink', 'OrangeRed', 'Red',
            'SeaGreen', 'SpringGreen', 'YellowGreen'
        ]
        
        # Rate limiting
        self.last_color_change = 0
        self.color_change_cooldown = 2  # seconds
        
        # Statistics
        self.messages_sent = 0
        self.colors_changed = 0
        self.start_time = datetime.now()
        
    async def event_ready(self):
        """Called when the bot is ready"""
        print_log(f'✅ Bot ready! Username: {self.nick}', bcolors.OKGREEN)
        print_log(f'📺 Monitoring channels: {", ".join(self.channels)}', bcolors.OKBLUE)
        print_log(f'🎨 Color mode: {"Random hex" if self.use_random_colors else "Preset colors"}', bcolors.OKCYAN)
        
        # Initialize aiohttp session
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        # Refresh token if needed
        if self.refresh_token and self.client_id and self.client_secret:
            await self.refresh_access_token()
            
        # Start periodic token refresh task
        asyncio.create_task(self.periodic_token_refresh())
    
    async def event_message(self, message):
        """Called when a message is received in chat"""
        # Only process messages from the bot user
        if message.author.name.lower() != self.nick.lower():
            return
        
        # Ignore messages that start with ! (commands)
        if message.content.startswith('!'):
            return
        
        self.messages_sent += 1
        print_log(f'📩 Message from {message.author.name}: {message.content}', bcolors.OKBLUE)
        
        # Change color after sending a message
        await self.change_color()
    
    async def event_raw_data(self, data):
        """Handle raw IRC data including PING/PONG"""
        try:
            if data.startswith('PING'):
                # Extract server from PING message
                server = data.split(' ', 1)[1].strip() if ' ' in data else ':tmi.twitch.tv'
                pong_response = f'PONG {server}'
                
                # Send PONG response to keep connection alive
                if hasattr(self, '_websocket') and self._websocket:
                    await self._websocket.send_str(pong_response)
                    print_log(f'🏓 Responded to PING with: {pong_response}', bcolors.OKCYAN)
        except Exception as e:
            print_log(f'⚠️ Error handling raw data: {e}', bcolors.WARNING)
    
    async def event_error(self, error):
        """Handle connection errors"""
        print_log(f'⚠️ Bot error: {error}', bcolors.WARNING)
        
        # Try to reconnect on connection errors
        if 'connection' in str(error).lower():
            print_log('🔄 Attempting to reconnect...', bcolors.OKBLUE)
    
    async def change_color(self):
        """Change the username color"""
        # Rate limiting
        current_time = time.time()
        if current_time - self.last_color_change < self.color_change_cooldown:
            print_log('⏳ Color change on cooldown', bcolors.WARNING)
            return
        
        self.last_color_change = current_time
        
        try:
            if self.use_random_colors:
                new_color = await self.get_random_hex_color()
            else:
                new_color = await self.get_preset_color()
            
            if new_color:
                success = await self.set_username_color(new_color)
                if success:
                    self.colors_changed += 1
                    self.update_color_history(new_color)
                    print_log(f'🎨 Color changed to: {new_color}', bcolors.OKGREEN)
                else:
                    print_log('❌ Failed to change color', bcolors.FAIL)
            
        except Exception as e:
            print_log(f'❌ Error changing color: {e}', bcolors.FAIL)
    
    async def get_random_hex_color(self) -> str:
        """Generate a random hex color"""
        while True:
            # Generate random RGB values
            r = random.randint(50, 255)  # Avoid very dark colors
            g = random.randint(50, 255)
            b = random.randint(50, 255)
            
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            
            # Make sure it's different from the last color
            if hex_color != self.last_color and hex_color not in self.color_history:
                return hex_color
    
    async def get_preset_color(self) -> str:
        """Get a preset Twitch color"""
        available_colors = [color for color in self.preset_colors 
                          if color != self.last_color and color not in self.color_history]
        
        if not available_colors:
            # If all colors have been used recently, reset and pick any except the last one
            available_colors = [color for color in self.preset_colors if color != self.last_color]
        
        return random.choice(available_colors) if available_colors else random.choice(self.preset_colors)
    
    def update_color_history(self, color: str):
        """Update the color history to avoid repeating recent colors"""
        self.last_color = color
        self.color_history.append(color)
        
        # Keep only the last few colors
        if len(self.color_history) > self.max_history:
            self.color_history.pop(0)
    
    async def set_username_color(self, color: str) -> bool:
        """Set the username color using Twitch API"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = "https://api.twitch.tv/helix/chat/color"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id,
            'Content-Type': 'application/json'
        }
        
        # Get user ID first
        user_id = await self.get_user_id()
        if not user_id:
            print_log('❌ Could not get user ID', bcolors.FAIL)
            return False
        
        params = {
            'user_id': user_id,
            'color': color
        }
        
        try:
            async with self.session.put(url, headers=headers, params=params) as response:
                if response.status == 204:
                    return True
                elif response.status == 401:
                    print_log('🔄 Access token expired, refreshing...', bcolors.WARNING)
                    if await self.refresh_access_token():
                        # Retry with new token
                        headers['Authorization'] = f'Bearer {self.access_token}'
                        async with self.session.put(url, headers=headers, params=params) as retry_response:
                            return retry_response.status == 204
                    return False
                else:
                    error_text = await response.text()
                    print_log(f'❌ API Error {response.status}: {error_text}', bcolors.FAIL)
                    return False
                    
        except Exception as e:
            print_log(f'❌ Network error: {e}', bcolors.FAIL)
            return False
    
    async def get_user_id(self) -> Optional[str]:
        """Get the user ID for the current user"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = "https://api.twitch.tv/helix/users"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        
        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    users = data.get('data', [])
                    if users:
                        return users[0]['id']
                else:
                    print_log(f'❌ Failed to get user ID: {response.status}', bcolors.FAIL)
                    return None
                    
        except Exception as e:
            print_log(f'❌ Error getting user ID: {e}', bcolors.FAIL)
            return None
    
    async def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token"""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            print_log('⚠️ Missing refresh token or client credentials', bcolors.WARNING)
            return False
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = "https://id.twitch.tv/oauth2/token"
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            async with self.session.post(url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self.access_token = token_data['access_token']
                    
                    # Update refresh token if provided
                    if 'refresh_token' in token_data:
                        self.refresh_token = token_data['refresh_token']
                    
                    # Calculate token expiry
                    if 'expires_in' in token_data:
                        self.token_expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
                    
                    # Save updated tokens to config file if available
                    if self.config_file:
                        self.save_tokens_to_config()
                    
                    print_log('✅ Access token refreshed successfully', bcolors.OKGREEN)
                    return True
                else:
                    error_text = await response.text()
                    print_log(f'❌ Failed to refresh token: {response.status} - {error_text}', bcolors.FAIL)
                    return False
                    
        except Exception as e:
            print_log(f'❌ Error refreshing token: {e}', bcolors.FAIL)
            return False
    
    async def periodic_token_refresh(self):
        """Periodically refresh tokens to keep them valid"""
        while True:
            try:
                # Check if token is expiring soon (refresh 1 hour before expiry)
                if self.token_expiry:
                    time_until_expiry = self.token_expiry - datetime.now()
                    if time_until_expiry <= timedelta(hours=1):
                        print_log('🔄 Token expiring soon, refreshing...', bcolors.WARNING)
                        await self.refresh_access_token()
                else:
                    # If no expiry info, refresh every 24 hours as a safety measure
                    print_log('🔄 Performing periodic token refresh...', bcolors.OKBLUE)
                    await self.refresh_access_token()
                
                # Wait 1 hour before checking again
                await asyncio.sleep(3600)  # 1 hour
                
            except asyncio.CancelledError:
                print_log('⏹️ Token refresh task cancelled', bcolors.WARNING)
                break
            except Exception as e:
                print_log(f'⚠️ Error in periodic token refresh: {e}', bcolors.WARNING)
                # Wait 10 minutes before retrying
                await asyncio.sleep(600)
    
    def save_tokens_to_config(self):
        """Save updated tokens back to the config file"""
        if not self.config_file:
            return
        
        try:
            from .config import update_user_in_config
            
            # Prepare updated user config
            updated_config = {
                'username': self.nick,
                'access_token': self.access_token,  # Save clean token without oauth prefix
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'channels': self.channels,
                'use_random_colors': self.use_random_colors
            }
            
            # Update config file
            if update_user_in_config(updated_config, self.config_file):
                print_log(f'💾 Tokens saved for user {self.nick}', bcolors.OKGREEN)
            else:
                print_log(f'⚠️ Failed to save tokens for user {self.nick}', bcolors.WARNING)
                
        except Exception as e:
            print_log(f'❌ Error saving tokens: {e}', bcolors.FAIL)
    
    def print_statistics(self):
        """Print bot statistics"""
        uptime = datetime.now() - self.start_time
        print_log(f"\n📊 Bot Statistics for {self.nick}:", bcolors.HEADER)
        print_log(f"⏱️ Uptime: {uptime}")
        print_log(f"📩 Messages sent: {self.messages_sent}")
        print_log(f"🎨 Colors changed: {self.colors_changed}")
        print_log(f"📺 Channels: {', '.join(self.channels)}")
        if self.last_color:
            print_log(f"🎯 Current color: {self.last_color}")
    
    async def close(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        await super().close()
        print_log(f'👋 Bot {self.nick} disconnected', bcolors.OKBLUE)
