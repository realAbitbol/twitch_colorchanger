#!/usr/bin/env python3
"""
Automatic Twitch Color Changer Bot
Connects to Twitch IRC to detect messages and changes username color via Twitch API
after each message you send in any channel.
"""

import socket
import time
import random
import threading
import re
import json
import requests
import os
from datetime import datetime, timedelta

class bcolors:
    HEADER = '\033[35m'  # Magenta (standard)
    OKBLUE = '\033[34m'  # Blue (standard)
    OKCYAN = '\033[36m'  # Cyan (standard)
    OKGREEN = '\033[32m'  # Green (standard)
    WARNING = '\033[33m'  # Yellow (standard)
    FAIL = '\033[31m'    # Red (standard)
    ENDC = '\033[0m'     # Reset
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_log(message, color=""):
    """Print log with ANSI colors if FORCE_COLOR is not false, else plain text"""
    use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    if use_colors:
        print(f"{color}{message}{bcolors.ENDC}")
    else:
        print(message)

class TwitchColorBot:
    def __init__(self, username, access_token, refresh_token, client_id, client_secret, channels=None, use_random_colors=False):
        self.username = username.lower()
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.channels = channels or []
        self.use_random_colors = use_random_colors
        
        # Token management
        self.token_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
        self.user_id = None
        self.load_saved_tokens()
        
        # Twitch IRC settings
        self.server = 'irc.chat.twitch.tv'
        self.port = 6667
        self.sock = None
        
        # Color management
        self.twitch_colors = [
            'Red', 'Blue', 'Green', 'FireBrick', 'Coral', 'YellowGreen',
            'OrangeRed', 'SeaGreen', 'GoldenRod', 'Chocolate', 'CadetBlue',
            'DodgerBlue', 'HotPink', 'BlueViolet', 'SpringGreen'
        ]
        self.current_color_index = 0
        self.last_color_change = datetime.min
        self.rate_limit_delay = 1.5  # 1.5-second rate limit
        
        # Track joined channels
        self.joined_channels = set()
        self.running = False
    
    def generate_random_hex_color(self):
        """Generate random hex color for Prime/Turbo users"""
        hue = random.randint(0, 359)
        saturation = random.randint(60, 100)
        lightness = random.randint(35, 75)
        c = (1 - abs(2 * lightness/100 - 1)) * saturation/100
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = lightness/100 - c/2
        
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
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def save_tokens(self):
        """Save tokens, username, channels, and random colors choice to file"""
        token_data = {
            'username': self.username,
            'channels': self.channels,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'user_id': self.user_id,
            'use_random_colors': self.use_random_colors,
            'saved_at': datetime.now().isoformat()
        }
        try:
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f, indent=2)
            print_log("💾 Tokens saved successfully", bcolors.OKGREEN)
        except Exception as e:
            print_log(f"⚠️ Failed to save tokens: {e}", bcolors.FAIL)
    
    def load_saved_tokens(self):
        """Load previously saved tokens, username, channels, and random colors choice"""
        try:
            with open(self.token_file, 'r') as f:
                token_data = json.load(f)
                
            if token_data.get('username', '').lower() == self.username:
                self.access_token = token_data.get('access_token', self.access_token)
                self.refresh_token = token_data.get('refresh_token', self.refresh_token)
                self.client_id = token_data.get('client_id', self.client_id)
                self.client_secret = token_data.get('client_secret', self.client_secret)
                self.user_id = token_data.get('user_id', self.user_id)
                self.channels = token_data.get('channels', self.channels)
                self.use_random_colors = token_data.get('use_random_colors', self.use_random_colors)
                print_log("📂 Loaded saved tokens", bcolors.OKCYAN)
                
        except FileNotFoundError:
            print_log("📝 No saved tokens found - will save after first successful connection", bcolors.WARNING)
        except Exception as e:
            print_log(f"⚠️ Error loading saved tokens: {e}", bcolors.FAIL)
    
    def get_user_id(self):
        """Fetch the user's Twitch ID"""
        url = "https://api.twitch.tv/helix/users"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        params = {'login': self.username}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['data']:
                    self.user_id = data['data'][0]['id']
                    print_log(f"✅ Fetched user ID: {self.user_id}", bcolors.OKGREEN)
                    return True
                else:
                    print_log(f"❌ No user found for username: {self.username}", bcolors.FAIL)
                    return False
            else:
                print_log(f"❌ Failed to fetch user ID: {response.status_code} - {response.text}", bcolors.FAIL)
                return False
        except Exception as e:
            print_log(f"❌ Error fetching user ID: {e}", bcolors.FAIL)
            return False
    
    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            print_log("❌ Cannot refresh token - missing refresh_token, client_id, or client_secret", bcolors.FAIL)
            return False
            
        refresh_url = "https://id.twitch.tv/oauth2/token"
        refresh_data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            print_log("🔄 Refreshing access token...", bcolors.HEADER)
            response = requests.post(refresh_url, data=refresh_data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                if 'refresh_token' in token_data:
                    self.refresh_token = token_data['refresh_token']
                print_log("✅ Token refreshed successfully!", bcolors.OKGREEN)
                self.save_tokens()
                return True
            else:
                print_log(f"❌ Token refresh failed: {response.status_code} - {response.text}", bcolors.FAIL)
                return False
                
        except Exception as e:
            print_log(f"❌ Token refresh error: {e}", bcolors.FAIL)
            return False
    
    def validate_token(self):
        """Validate current access token and check required scopes"""
        validation_url = "https://id.twitch.tv/oauth2/validate"
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        try:
            response = requests.get(validation_url, headers=headers, timeout=10)
            if response.status_code == 200:
                token_info = response.json()
                expires_in = token_info.get('expires_in', 0)
                hours = expires_in // 3600
                minutes = (expires_in % 3600) // 60
                scopes = token_info.get('scopes', [])
                print_log(f"✅ Token valid - expires in {hours} hours and {minutes} minutes, scopes: {scopes}", bcolors.OKGREEN)
                required_scopes = ['chat:read', 'user:manage:chat_color']
                missing_scopes = [scope for scope in required_scopes if scope not in scopes]
                if missing_scopes:
                    print_log(f"❌ Token missing required scopes: {missing_scopes}", bcolors.FAIL)
                    return False
                if expires_in < 3600:  # Only refresh if less than 1 hour left
                    print_log("⏰ Token expires in less than 1 hour, refreshing...", bcolors.WARNING)
                    return self.refresh_access_token()
                return True
            else:
                print_log("❌ Token validation failed, attempting refresh...", bcolors.FAIL)
                return self.refresh_access_token()
                
        except Exception as e:
            print_log(f"⚠️ Token validation error: {e}", bcolors.FAIL)
            return self.refresh_access_token()
    
    def token_refresher(self):
        """Background thread to auto-refresh token if about to expire"""
        while self.running:
            self.validate_token()
            time.sleep(300)  # Check every 5 minutes
    
    def get_oauth_token(self):
        """Get properly formatted OAuth token for IRC"""
        token = self.access_token
        if not token.startswith('oauth:'):
            token = 'oauth:' + token
        return token
    
    def get_next_color(self):
        """Get next color in rotation"""
        if self.use_random_colors:
            return self.generate_random_hex_color()
        else:
            color = self.twitch_colors[self.current_color_index]
            self.current_color_index = (self.current_color_index + 1) % len(self.twitch_colors)
            return color
    
    def can_change_color(self):
        """Check if enough time passed since last color change"""
        return (datetime.now() - self.last_color_change).total_seconds() >= self.rate_limit_delay
    
    def change_color(self, channel=None):
        """Change username color via Twitch API"""
        if not self.can_change_color():
            print_log("⏳ Rate limit active, skipping color change", bcolors.WARNING)
            return
        
        if not self.user_id:
            print_log("❌ User ID not available, fetching...", bcolors.FAIL)
            if not self.get_user_id():
                print_log("❌ Cannot change color without user ID", bcolors.FAIL)
                return
        
        if not self.validate_token():
            print_log("❌ Cannot change color with invalid token", bcolors.FAIL)
            return
        
        new_color = self.get_next_color()
        
        url = "https://api.twitch.tv/helix/chat/color"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        params = {
            'user_id': self.user_id,
            'color': new_color
        }
        
        try:
            print_log(f"🎨 Attempting to change color to {new_color} via API (token: {self.access_token[:5]}...)", bcolors.OKBLUE)
            response = requests.put(url, headers=headers, params=params, timeout=10)
            if response.status_code == 204:
                print_log(f"✅ Color changed to {new_color}", bcolors.OKGREEN)
                self.last_color_change = datetime.now()
                time.sleep(1)  # Brief delay to allow chat clients to update
            else:
                print_log(f"❌ Color change failed: {response.status_code} - {response.text}", bcolors.FAIL)
        except Exception as e:
            print_log(f"❌ Color change error: {e}", bcolors.FAIL)
    
    def connect(self):
        """Connect to Twitch IRC with automatic token validation/refresh"""
        if not self.validate_token():
            print_log("❌ Could not obtain valid token", bcolors.FAIL)
            return False
        
        if not self.user_id:
            if not self.get_user_id():
                print_log("❌ Could not obtain user ID", bcolors.FAIL)
                return False
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.server, self.port))
            
            formatted_token = self.get_oauth_token()
            self.sock.send(f"PASS {formatted_token}\r\n".encode('utf-8'))
            self.sock.send(f"NICK {self.username}\r\n".encode('utf-8'))
            
            self.sock.send("CAP REQ :twitch.tv/membership\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/tags\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/commands\r\n".encode('utf-8'))
            
            print_log(f"✅ Connected to Twitch IRC as {self.username}", bcolors.OKGREEN)
            self.save_tokens()
            return True
            
        except Exception as e:
            print_log(f"❌ Connection failed: {e}", bcolors.FAIL)
            return False
    
    def send_message(self, channel, message):
        """Send message to a channel"""
        try:
            formatted_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.sock.send(formatted_msg.encode('utf-8'))
            print_log(f"📤 Sent to #{channel}: {message}", bcolors.OKCYAN)
        except Exception as e:
            print_log(f"❌ Failed to send message: {e}", bcolors.FAIL)
    
    def join_channel(self, channel):
        """Join a Twitch channel"""
        channel = channel.lower().replace('#', '')
        self.sock.send(f"JOIN #{channel}\r\n".encode('utf-8'))
        self.joined_channels.add(channel)
        print_log(f"📺 Joined #{channel}", bcolors.OKBLUE)
    
    def parse_message(self, raw_message):
        """Parse IRC message and extract relevant info"""
        try:
            if raw_message.startswith('@'):
                parts = raw_message.split(' ', 3)
                if len(parts) >= 4:
                    tags = parts[0]
                    prefix = parts[1]
                    command = parts[2]
                    params = parts[3]
                else:
                    return None
            else:
                parts = raw_message.split(' ', 2)
                if len(parts) >= 3:
                    prefix = parts[0]
                    command = parts[1]
                    params = parts[2]
                    tags = ""
                else:
                    return None
            
            if '!' in prefix:
                sender = prefix.split('!')[0].replace(':', '')
            else:
                sender = prefix.replace(':', '')
            
            if command == 'PRIVMSG' and sender.lower() == self.username.lower():
                channel_msg = params.split(' :', 1)
                if len(channel_msg) >= 2:
                    channel = channel_msg[0].replace('#', '')
                    message = channel_msg[1]
                    print_log(f"📥 Received PRIVMSG from {sender} in #{channel}: {message[:50]}{'...' if len(message) > 50 else ''}", bcolors.OKBLUE)
                    return {
                        'sender': sender,
                        'channel': channel,
                        'message': message,
                        'command': command,
                        'raw': raw_message
                    }
            elif command == 'NOTICE':
                channel_msg = params.split(' :', 1)
                if len(channel_msg) >= 2:
                    channel = channel_msg[0].replace('#', '')
                    message = channel_msg[1]
                    print_log(f"⚠️ NOTICE from #{channel}: {message}", bcolors.WARNING)
                    return {
                        'sender': sender,
                        'channel': channel,
                        'message': message,
                        'command': command,
                        'raw': raw_message
                    }
            elif command == '366':  # RPL_ENDOFNAMES, confirms join
                channel = params.split(' ')[1].replace('#', '')
                print_log(f"✅ Successfully joined #{channel}", bcolors.OKGREEN)
                return None
            
            return None
            
        except Exception as e:
            print_log(f"⚠️ Parse error: {e}", bcolors.FAIL)
            return None
    
    def handle_message(self, parsed_msg):
        """Handle parsed IRC message"""
        if not parsed_msg:
            return
        
        if (parsed_msg.get('sender', '').lower() == self.username.lower() and 
            parsed_msg.get('command') == 'PRIVMSG'):
            
            message = parsed_msg.get('message', '')
            channel = parsed_msg.get('channel', '')
            
            print_log(f"💬 You sent in #{channel}: {message[:50]}{'...' if len(message) > 50 else ''}", bcolors.OKCYAN)
            threading.Timer(0.5, lambda: self.change_color(channel)).start()
    
    def listen(self):
        """Main listening loop"""
        buffer = ""
        
        while self.running:
            try:
                data = self.sock.recv(4096).decode('utf-8', errors='ignore')
                buffer += data
                
                while '\r\n' in buffer:
                    line, buffer = buffer.split('\r\n', 1)
                    
                    if line:
                        if line.startswith('PING'):
                            pong = line.replace('PING', 'PONG')
                            self.sock.send(f"{pong}\r\n".encode('utf-8'))
                            print_log("📡 Responded to PING with PONG", bcolors.OKCYAN)
                            continue
                        
                        parsed = self.parse_message(line)
                        self.handle_message(parsed)
                        
            except socket.timeout:
                continue
            except Exception as e:
                print_log(f"❌ Listen error: {e}", bcolors.FAIL)
                break
    
    def start(self, channels_to_join=None):
        """Start the bot"""
        if not self.connect():
            return
        
        self.running = True
        threading.Thread(target=self.token_refresher, daemon=True).start()
        time.sleep(2)
        
        if channels_to_join:
            for channel in channels_to_join:
                self.join_channel(channel)
        
        print_log(f"🤖 Bot started! Send messages in Chatterino and your color will change automatically.", bcolors.OKBLUE)
        print_log("🛑 Press Ctrl+C to stop", bcolors.OKBLUE)
        
        try:
            self.listen()
        except KeyboardInterrupt:
            print_log("\n🛑 Stopping bot...", bcolors.OKBLUE)
        finally:
            self.stop()
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        if self.sock:
            self.sock.close()
        print_log("👋 Bot stopped", bcolors.OKBLUE)

def main():
    print_log("🎨 Automatic Twitch Color Changer Bot", bcolors.HEADER)
    print_log("="*50)
    
    print_log("\n📝 Setup (one-time):")
    print_log("To enable automatic token refresh and color changes, you must create a Twitch app to get a Client ID and Client Secret.")
    print_log("Steps to create a Twitch app:")
    print_log("1. Go to https://dev.twitch.tv/console/apps and sign in with your Twitch account.")
    print_log("2. Click 'Register Your Application'.")
    print_log("3. Enter a name for your app (e.g., 'TwitchColorBot').")
    print_log("4. Set 'OAuth Redirect URLs' to: https://twitchtokengenerator.com")
    print_log("5. Set 'Category' to 'Chat Bot' or 'Other'.")
    print_log("6. Click 'Create'. Your Client ID will be displayed.")
    print_log("7. Click 'Manage' next to your app, then 'New Secret' to generate a Client Secret. Save both values.")
    print_log("8. On https://twitchtokengenerator.com, select 'Custom Token Generator'.")
    print_log("9. Enter your Client ID and Client Secret.")
    print_log("10. Select scopes: chat:read, user:manage:chat_color (chat:edit optional for sending messages)")
    print_log("11. Click 'Generate Token' and save the Access Token and Refresh Token.")
    print_log("\n🔗 Alternative token generators (require Client ID/Secret):")
    print_log("   • https://twitchapps.com/tokengen")
    print_log("   • https://www.twitchtools.com/chat-token")
    print_log("\n📋 Required scopes for IRC and color changes: chat:read, user:manage:chat_color (chat:edit optional)")
    print_log("⚠️ IMPORTANT: Save ALL FOUR values - Access Token, Refresh Token, Client ID, AND Client Secret")
    
    token_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
    
    # Get potential values from environment variables
    env_username = os.environ.get('TWITCH_USERNAME', '').strip()
    env_access_token = os.environ.get('TWITCH_ACCESS_TOKEN', '').strip()
    env_refresh_token = os.environ.get('TWITCH_REFRESH_TOKEN', '').strip()
    env_client_id = os.environ.get('TWITCH_CLIENT_ID', '').strip()
    env_client_secret = os.environ.get('TWITCH_CLIENT_SECRET', '').strip()
    env_channels_str = os.environ.get('TWITCH_CHANNELS', '').strip()
    env_use_random_colors = os.environ.get('TWITCH_USE_RANDOM_COLORS', None)
    
    # Determine if in env mode (unattended, e.g., Docker)
    is_env_mode = bool(env_username)  # If username is set via env, assume env mode
    
    # Load saved tokens if file exists
    saved_tokens = None
    try:
        with open(token_file, 'r') as f:
            saved_tokens = json.load(f)
        if not saved_tokens.get('username'):
            print_log("❌ Saved tokens missing username", bcolors.FAIL)
            saved_tokens = None
    except FileNotFoundError:
        print_log("📝 No saved tokens found", bcolors.WARNING)
    except Exception as e:
        print_log(f"⚠️ Error reading saved tokens: {e}", bcolors.FAIL)
        saved_tokens = None
    
    username = None
    access_token = None
    refresh_token = None
    client_id = None
    client_secret = None
    channels = []
    use_random_colors = False
    
    if is_env_mode:
        # In env mode, use env values, fall back to saved if matching username and value not set in env
        username = env_username
        if not username:
            print_log("❌ TWITCH_USERNAME is required in environment mode", bcolors.FAIL)
            return
        
        # Load saved only if username matches
        if saved_tokens and saved_tokens.get('username', '').lower() == username.lower():
            access_token = env_access_token if env_access_token else saved_tokens.get('access_token', '')
            refresh_token = env_refresh_token if env_refresh_token else saved_tokens.get('refresh_token', '')
            client_id = env_client_id if env_client_id else saved_tokens.get('client_id', '')
            client_secret = env_client_secret if env_client_secret else saved_tokens.get('client_secret', '')
            channels = [ch.strip().lower() for ch in env_channels_str.split(',') if ch.strip()] if env_channels_str else saved_tokens.get('channels', [])
            use_random_colors = (env_use_random_colors.lower() == 'true') if env_use_random_colors is not None else saved_tokens.get('use_random_colors', False)
        else:
            access_token = env_access_token
            refresh_token = env_refresh_token
            client_id = env_client_id
            client_secret = env_client_secret
            channels = [ch.strip().lower() for ch in env_channels_str.split(',') if ch.strip()] if env_channels_str else []
            use_random_colors = (env_use_random_colors.lower() == 'true') if env_use_random_colors is not None else False
        
        # Check for required values
        if not all([access_token, refresh_token, client_id, client_secret]):
            print_log("❌ Missing required values (check environment variables or saved config)", bcolors.FAIL)
            return
        print_log(f"✅ Using environment configuration for {username}", bcolors.OKGREEN)
    else:
        # Interactive mode
        if saved_tokens:
            print_log(f"\n💾 Found saved tokens for {saved_tokens.get('username', 'unknown')} with channels: {saved_tokens.get('channels', [])}", bcolors.OKCYAN)
            print("🔄 Load saved tokens and channels from twitch_colorchanger.conf? [Y/n]: ")
            use_saved = input().lower()
            if use_saved == '' or use_saved.startswith('y'):
                username = saved_tokens.get('username', '')
                access_token = saved_tokens.get('access_token', '')
                refresh_token = saved_tokens.get('refresh_token', '')
                client_id = saved_tokens.get('client_id', '')
                client_secret = saved_tokens.get('client_secret', '')
                channels = saved_tokens.get('channels', [])
                use_random_colors = saved_tokens.get('use_random_colors', False)
                print_log(f"✅ Using saved tokens and channels: {channels}", bcolors.OKGREEN)
            else:
                saved_tokens = None
        
        if not username:
            username = input("\n👤 Enter your Twitch username: ").strip()
        
        if not username:
            print_log("❌ Username cannot be empty", bcolors.FAIL)
            return
        
        if not access_token or not refresh_token or not client_id or not client_secret:
            print_log("\n🔑 From the token generator, you need ALL FOUR values:")
            access_token = input("🎫 Enter your ACCESS TOKEN: ").strip()
            refresh_token = input("🔄 Enter your REFRESH TOKEN: ").strip()
            client_id = input("📱 Enter your CLIENT ID: ").strip()
            client_secret = input("🔒 Enter your CLIENT SECRET: ").strip()
        
        if not access_token or not refresh_token or not client_id or not client_secret:
            print_log("❌ All four values are required for automatic refresh!", bcolors.FAIL)
            return
        
        print_log("\n📺 Enter channels to join (where you'll be chatting):")
        print_log("   Leave empty to join channels manually in Chatterino")
        channels_input = input("   Channels (comma-separated): ").strip()
        channels = [ch.strip().lower() for ch in channels_input.split(',') if ch.strip()]
        
        print_log("\n🎲 Use random hex colors? (recommended for Prime/Turbo users) [Y/n]: ")
        use_random_input = input().lower()
        use_random_colors = use_random_input == '' or use_random_input.startswith('y')
    
    try:
        bot = TwitchColorBot(username, access_token, refresh_token, client_id, client_secret, channels, use_random_colors=use_random_colors)
        print_log(f"\n🎨 Starting bot with {'random hex colors' if use_random_colors else 'preset colors'}...", bcolors.OKBLUE)
        bot.start(channels_to_join=channels)
    except KeyboardInterrupt:
        print_log("\n👋 Goodbye!", bcolors.OKBLUE)
    except Exception as e:
        print_log(f"❌ Error: {e}", bcolors.FAIL)

if __name__ == "__main__":
    main()
