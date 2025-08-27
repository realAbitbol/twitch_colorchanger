#!/usr/bin/env python3
"""
Twitch ColorChanger Bot - Multi-User Support
Automatically changes Twitch chat color every few minutes for multiple users
Supports Docker deployment with environment variables for unattended mode
"""

import os
import sys
import json
import time
import threading
import random
import socket
from datetime import datetime

import requests


class bcolors:
    """ANSI color codes for console output"""
    PURPLE = '\033[95m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

def print_log(message, color=""):
    """Print log with ANSI colors if FORCE_COLOR is not false, else plain text"""
    use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    if use_colors:
        print(f"{color}{message}{bcolors.ENDC}")
    else:
        print(message)

# Helper functions for multi-user support and unattended mode
def process_channels(channels_str):
    """Process comma-separated channel string into list of lowercase channel names"""
    return [ch.strip().lower() for ch in channels_str.split(',') if ch.strip()]


def load_users_from_env():
    """Load users from numbered environment variables (Docker unattended mode)"""
    users = []
    
    # First check for numbered environment variables (multi-user mode)
    for i in range(1, 100):  # Support up to 99 users
        username = os.environ.get(f'TWITCH_USERNAME_{i}')
        if not username:
            break
        
        user = {
            'username': username,
            'access_token': os.environ.get(f'TWITCH_ACCESS_TOKEN_{i}', ''),
            'refresh_token': os.environ.get(f'TWITCH_REFRESH_TOKEN_{i}', ''),
            'client_id': os.environ.get(f'TWITCH_CLIENT_ID_{i}', ''),
            'client_secret': os.environ.get(f'TWITCH_CLIENT_SECRET_{i}', ''),
            'channels': process_channels(os.environ.get(f'TWITCH_CHANNELS_{i}', '')),
            'use_random_colors': os.environ.get(f'TWITCH_USE_RANDOM_COLORS_{i}', 'false').lower() == 'true'
        }
        users.append(user)
    
    # If no numbered users found, check for legacy single-user environment variables
    if not users:
        legacy_username = os.environ.get('TWITCH_USERNAME')
        if legacy_username:
            user = {
                'username': legacy_username,
                'access_token': os.environ.get('TWITCH_ACCESS_TOKEN', ''),
                'refresh_token': os.environ.get('TWITCH_REFRESH_TOKEN', ''),
                'client_id': os.environ.get('TWITCH_CLIENT_ID', ''),
                'client_secret': os.environ.get('TWITCH_CLIENT_SECRET', ''),
                'channels': process_channels(os.environ.get('TWITCH_CHANNELS', '')),
                'use_random_colors': os.environ.get('TWITCH_USE_RANDOM_COLORS', 'false').lower() == 'true'
            }
            users.append(user)
    
    return users

def load_users_from_config(config_file):
    """Load users from config file"""
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
            # Support both new multi-user format and legacy single-user format
            if isinstance(data, dict) and 'users' in data:
                return data['users']
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'username' in data:
                # Legacy single-user format, convert to multi-user
                return [data]
            else:
                return []
    except FileNotFoundError:
        return []
    except Exception as e:
        print_log(f"⚠️ Error loading config: {e}", bcolors.FAIL)
        return []

def save_users_to_config(users, config_file):
    """Save users to config file"""
    try:
        with open(config_file, 'w') as f:
            json.dump({'users': users}, f, indent=2)
        print_log("💾 All users saved successfully", bcolors.OKGREEN)
    except Exception as e:
        print_log(f"⚠️ Failed to save users: {e}", bcolors.FAIL)

def prompt_for_user():
    """Prompt user to add a new user configuration"""
    print_log("Add a new Twitch user:", bcolors.HEADER)
    username = input("👤 Username: ").strip()
    access_token = input("🎫 Access Token: ").strip()
    refresh_token = input("🔄 Refresh Token: ").strip()
    client_id = input("📱 Client ID: ").strip()
    client_secret = input("🔒 Client Secret: ").strip()
    channels_input = input("📺 Channels (comma-separated): ").strip()
    channels = process_channels(channels_input)
    use_random_colors_input = input("🎲 Use random hex colors? [Y/n]: ").strip().lower()
    use_random_colors = use_random_colors_input in ['', 'y', 'yes']
    
    return {
        'username': username,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
        'channels': channels,
        'use_random_colors': use_random_colors
    }

def run_bot_for_user(user):
    """Run a bot instance for a specific user"""
    try:
        bot = TwitchColorBot(
            user['username'],
            user['access_token'],
            user['refresh_token'],
            user['client_id'],
            user['client_secret'],
            user.get('channels', []),
            use_random_colors=user.get('use_random_colors', False)
        )
        bot.start(channels_to_join=user.get('channels', []))
    except Exception as e:
        print_log(f"❌ Error running bot for {user['username']}: {e}", bcolors.FAIL)

def print_instructions():
    """Print setup instructions at launch"""
    print_log("🎨 Multi-User Twitch Color Changer Bot", bcolors.HEADER)
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
    
    print_log("\n🐳 Docker Multi-User Support:")
    print_log("Use numbered environment variables for each user:")
    print_log("   TWITCH_USERNAME_1, TWITCH_ACCESS_TOKEN_1, etc.")
    print_log("   TWITCH_USERNAME_2, TWITCH_ACCESS_TOKEN_2, etc.")

class TwitchColorBot:
    def __init__(self, username, access_token, refresh_token, client_id, client_secret, channels=None, use_random_colors=False):
        self.username = username.lower()
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.channels = channels or []
        self.use_random_colors = use_random_colors
        
        # Token management - use user-specific file for multi-user support
        base_config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
        self.token_file = base_config_file
        self.user_id = None
        self.load_saved_tokens()  # Load any saved data for this user
        
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
    
    def find_user_in_config(self, users):
        """Find user data in config by username (case insensitive)"""
        for i, user in enumerate(users):
            if user.get('username', '').lower() == self.username:
                return i, user
        return None, None

    def save_tokens(self):
        """Save tokens for this user back to the multi-user config file"""
        try:
            # Load existing config
            users = load_users_from_config(self.token_file)
            
            # Update or add this user's data
            user_data = {
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
            
            # Find and update existing user or add new one
            user_index, _ = self.find_user_in_config(users)
            if user_index is not None:
                users[user_index] = user_data
            else:
                users.append(user_data)
            
            save_users_to_config(users, self.token_file)
        except Exception as e:
            print_log(f"⚠️ Failed to save tokens for {self.username}: {e}", bcolors.FAIL)
    
    def load_saved_tokens(self):
        """Load previously saved tokens for this user from multi-user config"""
        try:
            users = load_users_from_config(self.token_file)
            _, user_data = self.find_user_in_config(users)
            
            if user_data:
                self.access_token = user_data.get('access_token', self.access_token)
                self.refresh_token = user_data.get('refresh_token', self.refresh_token)
                self.client_id = user_data.get('client_id', self.client_id)
                self.client_secret = user_data.get('client_secret', self.client_secret)
                self.user_id = user_data.get('user_id', self.user_id)
                self.channels = user_data.get('channels', self.channels)
                self.use_random_colors = user_data.get('use_random_colors', self.use_random_colors)
                print_log(f"📂 Loaded saved tokens for {self.username}", bcolors.OKCYAN)
            else:
                print_log(f"📝 No saved tokens found for {self.username} - will save after first successful connection", bcolors.WARNING)
        except Exception as e:
            print_log(f"⚠️ Error loading saved tokens for {self.username}: {e}", bcolors.FAIL)
    
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
    
    def change_color(self):
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
        
        if not self.user_id and not self.get_user_id():
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
    
    def extract_message_parts(self, raw_message):
        """Extract prefix, command, and params from IRC message"""
        if raw_message.startswith('@'):
            parts = raw_message.split(' ', 3)
            if len(parts) >= 4:
                return parts[1], parts[2], parts[3]
        else:
            parts = raw_message.split(' ', 2)
            if len(parts) >= 3:
                return parts[0], parts[1], parts[2]
        return None, None, None
    
    def extract_sender(self, prefix):
        """Extract sender name from prefix"""
        if '!' in prefix:
            return prefix.split('!')[0].replace(':', '')
        return prefix.replace(':', '')
    
    def parse_channel_message(self, params):
        """Parse channel and message from params"""
        channel_msg = params.split(' :', 1)
        if len(channel_msg) >= 2:
            channel = channel_msg[0].replace('#', '')
            message = channel_msg[1]
            return channel, message
        return None, None

    def handle_privmsg_command(self, sender, params, raw_message):
        """Handle PRIVMSG command"""
        channel, message = self.parse_channel_message(params)
        if channel is not None and message is not None:
            print_log(f"📥 Received PRIVMSG from {sender} in #{channel}: {message[:50]}{'...' if len(message) > 50 else ''}", bcolors.OKBLUE)
            return {
                'sender': sender,
                'channel': channel,
                'message': message,
                'command': 'PRIVMSG',
                'raw': raw_message
            }
        return None
    
    def handle_notice_command(self, sender, params, raw_message):
        """Handle NOTICE command"""
        channel, message = self.parse_channel_message(params)
        if channel is not None and message is not None:
            print_log(f"⚠️ NOTICE from #{channel}: {message}", bcolors.WARNING)
            return {
                'sender': sender,
                'channel': channel,
                'message': message,
                'command': 'NOTICE',
                'raw': raw_message
            }
        return None

    def parse_message(self, raw_message):
        """Parse IRC message and extract relevant info"""
        try:
            prefix, command, params = self.extract_message_parts(raw_message)
            if not prefix or not command or not params:
                return None
            
            sender = self.extract_sender(prefix)
            
            if command == 'PRIVMSG' and sender.lower() == self.username:
                return self.handle_privmsg_command(sender, params, raw_message)
            elif command == 'NOTICE':
                return self.handle_notice_command(sender, params, raw_message)
            elif command == '366':  # RPL_ENDOFNAMES, confirms join
                channel = params.split(' ')[1].replace('#', '')
                print_log(f"✅ Successfully joined #{channel}", bcolors.OKGREEN)
            
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
            threading.Timer(0.5, lambda: self.change_color()).start()
    
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
        
        print_log("🤖 Bot started! Send messages in Chatterino and your color will change automatically.", bcolors.OKBLUE)
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

def setup_interactive_users(config_file):
    """Handle interactive user setup and return list of users"""
    users = load_users_from_config(config_file)
    
    if not users:
        print_log("No users found in config. Let's add your first user.", bcolors.WARNING)
        users.append(prompt_for_user())
        save_users_to_config(users, config_file)
    
    # Ask if user wants to add more users
    while True:
        add_more = input("\nAdd another user? [y/N]: ").strip().lower()
        if add_more in ['y', 'yes']:
            users.append(prompt_for_user())
            save_users_to_config(users, config_file)
        else:
            break
    
    return users

def launch_user_bots(users):
    """Launch bot threads for all valid users"""
    threads = []
    for user in users:
        if not all([user.get('username'), user.get('access_token'), user.get('refresh_token'), 
                   user.get('client_id'), user.get('client_secret')]):
            print_log(f"⚠️ Skipping user {user.get('username', 'unknown')} - missing required credentials", bcolors.WARNING)
            continue
            
        t = threading.Thread(target=run_bot_for_user, args=(user,), daemon=True)
        t.start()
        threads.append(t)
        print_log(f"✅ Started bot for {user['username']}", bcolors.OKGREEN)
    
    return threads

def main():
    """Main function - handles multi-user setup and launches bots"""
    print_instructions()
    
    config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
    
    # First, try to load users from environment variables (Docker unattended mode)
    env_users = load_users_from_env()
    if env_users:
        users = env_users
        print_log(f"✅ Loaded {len(users)} users from environment variables.", bcolors.OKGREEN)
    else:
        # Interactive mode - load from config file or prompt user
        users = setup_interactive_users(config_file)
    
    # Launch bots for all users
    threads = launch_user_bots(users)
    
    if not threads:
        print_log("❌ No valid users to run bots for. Check your configuration.", bcolors.FAIL)
        return
    
    print_log(f"\n🤖 {len(threads)} bots running! Send messages in Chatterino and your colors will change automatically.", bcolors.OKBLUE)
    print_log("🛑 Press Ctrl+C to stop all bots", bcolors.OKBLUE)
    
    try:
        # Keep main thread alive
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print_log("\n🛑 Stopping all bots...", bcolors.WARNING)

if __name__ == "__main__":
    main()
