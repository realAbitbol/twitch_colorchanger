# Implementation Guide - Twitch Color Changer Bot

## Quick Start Implementation

### Step 1: Project Structure Setup

```text
twitch_colorchanger/
├── main.py                     # Entry point
├── requirements.txt            # Dependencies
├── Dockerfile                  # Container definition
├── docker-compose.yml-sample   # Deployment template
├── twitch_colorchanger.conf    # Runtime config (auto-generated)
└── src/
    ├── __init__.py
    ├── bot.py                  # Core bot logic
    ├── bot_manager.py          # Multi-bot orchestration
    ├── config.py               # Configuration management
    ├── simple_irc.py           # IRC client implementation
    ├── colors.py               # Color generation and console formatting
    └── utils.py                # Utilities and logging
```

### Step 2: Core Dependencies

```python

# requirements.txt

requests>=2.31.0,<3.0.0
aiohttp>=3.9.0,<4.0.0

```

### Step 3: Essential Implementation Components

#### A. Main Entry Point (`main.py`)

```python
#!/usr/bin/env python3
import asyncio
import sys
import os
from src.config import get_configuration, print_config_summary
from src.bot_manager import run_bots
from src.utils import print_instructions, print_log
from src.colors import bcolors

async def main():
    try:
        print_instructions()
        users_config = get_configuration()
        print_config_summary(users_config)
        config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
        await run_bots(users_config, config_file)
    except KeyboardInterrupt:
        print_log("\n⌨️ Interrupted by user", bcolors.WARNING)
    except Exception as e:
        print_log(f"\n❌ Fatal error: {e}", bcolors.FAIL)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

```

#### B. Color Generation System (`src/colors.py`)

```python
import random

class bcolors:
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    # ... additional colors

def generate_random_hex_color():
    """Generate random hex color using HSL for better distribution"""
    hue = random.randint(0, 359)
    saturation = random.randint(60, 100)
    lightness = random.randint(35, 75)
    
    # HSL to RGB conversion

    c = (1 - abs(2 * lightness/100 - 1)) * saturation/100

    x = c * (1 - abs((hue / 60) % 2 - 1))

    m = lightness/100 - c/2

    
    if 0 <= hue < 60:

        r, g, b = c, x, 0
    elif 60 <= hue < 120:

        r, g, b = x, c, 0
    # ... continue for all hue ranges

    
    r = int((r + m) * 255)
    g = int((g + m) * 255)
    b = int((b + m) * 255)
    
    return f"#{r:02x}{g:02x}{b:02x}"

def get_twitch_colors():
    return ['blue', 'blue_violet', 'cadet_blue', 'chocolate', 'coral',
            'dodger_blue', 'firebrick', 'golden_rod', 'green', 'hot_pink',
            'orange_red', 'red', 'sea_green', 'spring_green', 'yellow_green']

```

#### C. IRC Client Implementation (`src/simple_irc.py`)

```python
import socket
from typing import Optional

class SimpleTwitchIRC:
    def __init__(self):
        self.server = 'irc.chat.twitch.tv'
        self.port = 6667
        self.sock = None
        self.connected = False
        self.running = False
        self.message_handler = None
        
    def connect(self, token: str, username: str, channel: str) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.server, self.port))
            
            # OAuth authentication

            oauth_token = token if token.startswith('oauth:') else f'oauth:{token}'
            self.sock.send(f"PASS {oauth_token}\r\n".encode('utf-8'))
            self.sock.send(f"NICK {username}\r\n".encode('utf-8'))
            
            # Request Twitch-specific capabilities

            self.sock.send("CAP REQ :twitch.tv/membership\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/tags\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/commands\r\n".encode('utf-8'))
            
            self.connected = True
            self.running = True
            return True
        except Exception as e:
            print(f"IRC connection failed: {e}")
            return False
    
    def join_channel(self, channel: str):
        if self.sock and self.connected:
            channel = channel.lower().replace('#', '')
            self.sock.send(f"JOIN #{channel}\r\n".encode('utf-8'))
    
    def parse_message(self, raw_message: str) -> Optional[dict]:
        # Parse IRC PRIVMSG format: :user!user@user.tmi.twitch.tv PRIVMSG #channel :message

        try:
            parts = raw_message.split(' ', 3)
            if len(parts) >= 4 and parts[1] == 'PRIVMSG':

                sender = parts[0].split('!')[0].replace(':', '')
                channel = parts[2].replace('#', '')
                message = parts[3].replace(':', '', 1)
                return {'sender': sender, 'channel': channel, 'message': message}
            return None
        except Exception:
            return None
    
    def listen(self):
        buffer = ""
        while self.running and self.connected:
            try:
                data = self.sock.recv(4096).decode('utf-8', errors='ignore')
                if not data:
                    break
                
                buffer += data
                while '\r\n' in buffer:
                    line, buffer = buffer.split('\r\n', 1)
                    
                    if line.startswith('PING'):
                        # Respond to keepalive

                        pong = line.replace('PING', 'PONG')
                        self.sock.send(f"{pong}\r\n".encode('utf-8'))
                    else:
                        parsed = self.parse_message(line)
                        if parsed and self.message_handler:
                            self.message_handler(parsed['sender'], parsed['channel'], parsed['message'])
                            
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Listen error: {e}")
                break

```

#### D. Core Bot Logic (`src/bot.py`)

```python
import asyncio
import random
from datetime import datetime, timedelta
import aiohttp
from urllib.parse import quote

class TwitchColorBot:
    def __init__(self, token: str, refresh_token: str, client_id: str, 
                 client_secret: str, nick: str, channels: list, 
                 use_random_colors: bool = True, config_file: str = None, user_id: str = None):
        self.username = nick
        self.access_token = token.replace('oauth:', '')
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.channels = channels
        self.use_random_colors = use_random_colors
        self.config_file = config_file
        self.irc = None
        self.running = False
        self.messages_sent = 0
        self.colors_changed = 0
    
    async def start(self):
        self.running = True
        await self.check_and_refresh_token()
        
        # Get user_id if not set

        if not self.user_id:
            user_info = await self.get_user_info()
            if user_info and 'id' in user_info:
                self.user_id = user_info['id']
        
        # Setup IRC

        from .simple_irc import SimpleTwitchIRC
        self.irc = SimpleTwitchIRC()
        self.irc.connect(self.access_token, self.username, self.channels[0])
        
        for channel in self.channels:
            self.irc.join_channel(channel)
        
        self.irc.set_message_handler(self.handle_irc_message)
        
        # Start background tasks

        token_task = asyncio.create_task(self._periodic_token_check())
        loop = asyncio.get_event_loop()
        irc_task = loop.run_in_executor(None, self.irc.listen)
        
        await asyncio.gather(token_task, irc_task, return_exceptions=True)
    
    def handle_irc_message(self, sender: str, channel: str, message: str):
        if sender.lower() == self.username.lower():
            self.messages_sent += 1
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(self.delayed_color_change(), loop)
            except RuntimeError:
                import threading
                threading.Thread(target=lambda: asyncio.run(self.change_color()), daemon=True).start()
    
    async def delayed_color_change(self):
        await asyncio.sleep(random.uniform(1, 3))  # Random delay

        await self.change_color()
    
    async def change_color(self):
        if self.use_random_colors:
            from .colors import generate_random_hex_color
            color = generate_random_hex_color()
        else:
            from .colors import get_twitch_colors
            color = random.choice(get_twitch_colors())
        
        # URL encode for API

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
                        print(f"✅ {self.username}: Color changed to {color}")
                    else:
                        error_text = await response.text()
                        print(f"❌ {self.username}: Failed to change color. Status: {response.status}")
        except Exception as e:
            print(f"❌ {self.username}: Error changing color: {e}")
    
    async def _periodic_token_check(self):
        while self.running:
            await asyncio.sleep(600)  # 10 minutes

            if self.running:
                await self.check_and_refresh_token()
    
    async def check_and_refresh_token(self):
        # Implementation for token validation and refresh

        # Check expiry, refresh if needed, update config

        pass
    
    async def get_user_info(self):
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
                        return data.get('data', [{}])[0] if data.get('data') else None
        except Exception:
            return None

```

### Step 4: Configuration Management

#### Environment Variable Pattern

```python

# Multi-user Docker configuration

def get_docker_config():
    users = []
    user_num = 1
    
    while True:
        username = os.environ.get(f'TWITCH_USERNAME_{user_num}')
        access_token = os.environ.get(f'TWITCH_ACCESS_TOKEN_{user_num}')
        
        if not username or not access_token:
            break
            
        user_config = {
            'username': username,
            'access_token': access_token,
            'refresh_token': os.environ.get(f'TWITCH_REFRESH_TOKEN_{user_num}', ''),
            'client_id': os.environ.get(f'TWITCH_CLIENT_ID_{user_num}', ''),
            'client_secret': os.environ.get(f'TWITCH_CLIENT_SECRET_{user_num}', ''),
            'channels': process_channels(os.environ.get(f'TWITCH_CHANNELS_{user_num}', username)),
            'use_random_colors': os.environ.get(f'USE_RANDOM_COLORS_{user_num}', 'true').lower() == 'true'
        }
        users.append(user_config)
        user_num += 1
    
    return users

```

### Step 5: Docker Implementation

#### Dockerfile Pattern

```dockerfile
FROM python:3.13-alpine
WORKDIR /app

# Security: non-root user

RUN addgroup -g 1001 -S appgroup && \

    adduser -u 1001 -S appuser -G appgroup

# Dependencies

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application

COPY --chown=appuser:appgroup . .
USER appuser

# Configuration

ENV TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf
VOLUME ["/app/config"]

# Health check

HEALTHCHECK --interval=30s --timeout=10s \
    CMD python -c "from src.config import get_docker_config; exit(0 if get_docker_config() else 1)"

CMD ["python", "main.py"]

```

### Step 6: Bot Manager for Multi-User Support

```python
class BotManager:
    def __init__(self, users_config: list, config_file: str = None):
        self.users_config = users_config
        self.config_file = config_file
        self.bots = []
        self.tasks = []
    
    async def start_all_bots(self):
        for user_config in self.users_config:
            bot = TwitchColorBot(**user_config, config_file=self.config_file)
            self.bots.append(bot)
            task = asyncio.create_task(bot.start())
            self.tasks.append(task)
        
        await asyncio.gather(*self.tasks, return_exceptions=True)

```

### Step 7: Key Implementation Details

#### Message Flow

1. IRC message received → `SimpleTwitchIRC.parse_message()`
2. If sender matches bot username → `TwitchColorBot.handle_irc_message()`
3. Random delay 1-3 seconds → `delayed_color_change()`

4. Generate color → `change_color()`
5. API call to Twitch → Success/failure logging

#### Token Management

1. Check every 10 minutes → `_periodic_token_check()`

2. Validate current token → API call to `/helix/users`
3. If expired or expiring soon → `refresh_access_token()`
4. Update configuration file → `update_user_in_config()`

#### Error Handling Patterns

```python
try:
    # Operation

    pass
except Exception as e:
    print_log(f"❌ Error context: {e}", bcolors.FAIL)
    # Graceful fallback

```

This implementation guide provides the essential code structure and patterns needed to recreate the complete Twitch Color Changer Bot functionality.
