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

# Core dependencies for Twitch ColorChanger Bot
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

## Enhanced Implementation Features (2024 Improvements)

### Structured Logging Implementation

#### Core Logger Class (`src/logger.py`)

```python
import logging
import json
import os
from typing import Optional, Dict, Any

class BotLogger:
    """Enhanced logging with JSON and colored output support"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._setup_logger()
    
    def _setup_logger(self):
        # Configure based on environment
        debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
        log_format = os.getenv('LOG_FORMAT', 'colored').lower()
        log_file = os.getenv('LOG_FILE')
        
        level = logging.DEBUG if debug_mode else logging.INFO
        self.logger.setLevel(level)
        
        # Console handler
        console_handler = logging.StreamHandler()
        if log_format == 'json':
            console_handler.setFormatter(self._get_json_formatter())
        else:
            console_handler.setFormatter(self._get_colored_formatter())
        self.logger.addHandler(console_handler)
        
        # Optional file handler
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(self._get_json_formatter())
            self.logger.addHandler(file_handler)
    
    def log_api_request(self, endpoint: str, method: str, **context):
        """Log API requests with contextual information"""
        self.logger.info(f"API {method} {endpoint}", extra={
            'api_endpoint': endpoint,
            'http_method': method,
            **context
        })
```

#### Usage in Bot Classes

```python
from src.logger import BotLogger

class TwitchColorBot:
    def __init__(self, ...):
        self.logger = BotLogger(f"bot.{self.username}")
        
    async def change_color(self):
        self.logger.info("Changing color", user=self.username, channel=self.current_channel)
        try:
            response = await self.api_request(...)
            self.logger.log_api_request("/helix/chat/color", "PUT", 
                                      user=self.username, response_time=response_time)
        except Exception as e:
            self.logger.error("Color change failed", user=self.username, error=str(e))
```

### Configuration Validation Implementation

#### Validator Class (`src/config_validator.py`)

```python
import re
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    info: List[str]

class ConfigValidator:
    """Comprehensive configuration validation"""
    
    # Regex patterns
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,25}$')
    ACCESS_TOKEN_PATTERN = re.compile(r'^[a-zA-Z0-9]{30,}$')
    REFRESH_TOKEN_PATTERN = re.compile(r'^[a-zA-Z0-9]{50,}$')
    CLIENT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9]{30}$')
    
    def validate_user_config(self, user_config: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        info = []
        
        # Username validation
        username = user_config.get('username', '')
        if not self.USERNAME_PATTERN.match(username):
            errors.append(f"Invalid username format: {username}")
        
        # Token validation
        access_token = user_config.get('access_token', '')
        if not self.ACCESS_TOKEN_PATTERN.match(access_token):
            errors.append("Invalid access token format")
        
        # Security checks
        if 'your_token_here' in access_token.lower():
            errors.append("Placeholder token detected")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            info=info
        )
```

### Enhanced Error Handling Implementation

#### Exception Hierarchy (`src/error_handling.py`)

```python
from enum import Enum
from typing import Optional, Dict, Any
import time
import asyncio

class ErrorCategory(Enum):
    NETWORK = "network"
    API = "api"
    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    IRC = "irc"
    RATE_LIMIT = "rate_limit"

class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class BaseError(Exception):
    """Base exception with context"""
    def __init__(self, message: str, category: ErrorCategory, 
                 severity: ErrorSeverity, **context):
        super().__init__(message)
        self.category = category
        self.severity = severity
        self.context = context
        self.timestamp = time.time()

class NetworkError(BaseError):
    def __init__(self, message: str, status_code: Optional[int] = None, **context):
        super().__init__(message, ErrorCategory.NETWORK, ErrorSeverity.MEDIUM,
                        status_code=status_code, **context)

class APIError(BaseError):
    def __init__(self, message: str, status_code: int, endpoint: str, **context):
        super().__init__(message, ErrorCategory.API, ErrorSeverity.HIGH,
                        status_code=status_code, endpoint=endpoint, **context)

# Error handling decorator
def with_error_handling(max_retries: int = 3, backoff_factor: float = 1.5):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (NetworkError, APIError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        await asyncio.sleep(wait_time)
                    continue
                except Exception as e:
                    # Non-retryable error
                    raise
            
            raise last_exception
        return wrapper
    return decorator

# Usage in bot methods
class TwitchColorBot:
    @with_error_handling(max_retries=3)
    async def change_color(self):
        # Method implementation with automatic retry
        pass
```

### HTTP Connection Pooling Implementation

#### Connection Pool Manager (`src/http_client.py`)

```python
import aiohttp
import asyncio
import time
from typing import Dict, Any, Optional

class ConnectionPoolConfig:
    """Configuration for HTTP connection pool"""
    def __init__(self):
        self.max_connections = 50
        self.max_connections_per_host = 10
        self.keepalive_timeout = 60
        self.connect_timeout = 10
        self.read_timeout = 15
        self.total_timeout = 30
        self.enable_cleanup_closed = True

class ConnectionPool:
    """HTTP connection pool with session management"""
    
    def __init__(self, config: ConnectionPoolConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session_created_at = 0
        self._request_count = 0
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with connection pooling"""
        current_loop = asyncio.get_running_loop()
        
        # Create new session if needed or if loop changed
        if (self._session is None or self._session.closed or 
            self._loop != current_loop):
            await self._create_new_session()
        
        return self._session
    
    async def _create_new_session(self):
        """Create new HTTP session with optimized settings"""
        # Clean up existing session safely
        if self._session and not self._session.closed:
            try:
                current_loop = asyncio.get_running_loop()
                if self._loop == current_loop:
                    await self._session.close()
                else:
                    # Force close for cross-loop sessions
                    self._force_close_cross_loop_session()
            except Exception:
                pass
            finally:
                self._session = None
        
        # Configure connector for connection pooling
        connector = aiohttp.TCPConnector(
            limit=self.config.max_connections,
            limit_per_host=self.config.max_connections_per_host,
            keepalive_timeout=self.config.keepalive_timeout,
            enable_cleanup_closed=self.config.enable_cleanup_closed,
            force_close=False,
            use_dns_cache=True
        )
        
        # Create session with disabled timeout (we handle our own)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=None)
        )
        
        self._loop = asyncio.get_running_loop()
        self._session_created_at = time.time()
        self._request_count = 0
    
    def _force_close_cross_loop_session(self):
        """Force close session from different event loop"""
        try:
            if hasattr(self._session, '_connector') and self._session._connector:
                connector = self._session._connector
                connector._close()
                if hasattr(connector, '_conns'):
                    connector._conns.clear()
            self._session._closed = True
        except Exception:
            pass

class HTTPClient:
    """HTTP client with Twitch API support"""
    
    def __init__(self):
        self.pool = ConnectionPool(ConnectionPoolConfig())
    
    async def twitch_api_request(self, method: str, endpoint: str, 
                               access_token: str, client_id: str, **kwargs):
        """Make authenticated Twitch API request"""
        url = f"https://api.twitch.tv/helix/{endpoint}"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Client-Id': client_id,
            'Content-Type': 'application/json'
        }
        
        session = await self.pool.get_session()
        async with session.request(method, url, headers=headers, **kwargs) as response:
            response_data = await response.json() if response.content_length else {}
            return response_data, response.status, dict(response.headers)

# Global client instance
_global_http_client: Optional[HTTPClient] = None

def get_http_client() -> HTTPClient:
    """Get or create global HTTP client"""
    global _global_http_client
    if _global_http_client is None:
        _global_http_client = HTTPClient()
    return _global_http_client

async def close_http_client():
    """Clean up global HTTP client"""
    global _global_http_client
    if _global_http_client:
        try:
            await _global_http_client.pool.close()
        finally:
            _global_http_client = None
```

### Memory Monitoring Implementation

#### Memory Monitor (`src/memory_monitor.py`)

```python
import gc
import time
from typing import Dict, Any, List

class MemoryMonitor:
    """Monitor for potential memory leaks"""
    
    def __init__(self):
        self.baseline_objects = {}
        self.baseline_set = False
    
    def set_baseline(self):
        """Set baseline memory usage"""
        gc.collect()
        self.baseline_objects = self._count_objects()
        self.baseline_set = True
    
    def check_leaks(self) -> Dict[str, Any]:
        """Check for potential memory leaks"""
        if not self.baseline_set:
            self.set_baseline()
            return {'status': 'baseline_set'}
        
        gc.collect()
        current_objects = self._count_objects()
        
        leaks = {}
        for obj_type, current_count in current_objects.items():
            baseline_count = self.baseline_objects.get(obj_type, 0)
            increase = current_count - baseline_count
            
            # Flag significant increases
            if increase > max(baseline_count * 0.5, 10):
                leaks[obj_type] = {
                    'baseline': baseline_count,
                    'current': current_count,
                    'increase': increase
                }
        
        return {
            'status': 'checked',
            'potential_leaks': leaks,
            'total_objects': sum(current_objects.values())
        }
    
    def _count_objects(self) -> Dict[str, int]:
        """Count objects by type"""
        object_counts = {}
        for obj in gc.get_objects():
            obj_type = type(obj).__name__
            object_counts[obj_type] = object_counts.get(obj_type, 0) + 1
        return object_counts
```

### Integration Example

#### Enhanced Bot Class

```python
from src.logger import BotLogger
from src.http_client import get_http_client
from src.error_handling import with_error_handling, APIError
from src.memory_monitor import MemoryMonitor

class TwitchColorBot:
    def __init__(self, ...):
        self.logger = BotLogger(f"bot.{self.username}")
        self.http_client = get_http_client()
        self.memory_monitor = MemoryMonitor()
        self.memory_monitor.set_baseline()
    
    @with_error_handling(max_retries=3)
    async def change_color(self):
        """Enhanced color change with all improvements"""
        # Memory leak check (periodic)
        if self._should_check_memory():
            leak_report = self.memory_monitor.check_leaks()
            if leak_report.get('potential_leaks'):
                self.logger.warning("Memory leaks detected", extra=leak_report)
        
        # Generate color
        color = self._generate_color()
        
        # Log the operation
        self.logger.info("Changing color", user=self.username, color=color)
        
        try:
            # Make API request with connection pooling
            start_time = time.time()
            data, status, headers = await self.http_client.twitch_api_request(
                'PUT', 'chat/color', self.access_token, self.client_id,
                params={'user_id': self.user_id, 'color': color}
            )
            response_time = time.time() - start_time
            
            # Log success
            self.logger.log_api_request("/helix/chat/color", "PUT",
                                      user=self.username, 
                                      response_time=response_time,
                                      status_code=status)
            
            if status == 204:
                self.logger.info("Color changed successfully", 
                               user=self.username, color=color)
                self.last_color = color
                self.colors_changed += 1
            else:
                raise APIError(f"Unexpected status code: {status}", 
                             status_code=status, endpoint="/helix/chat/color")
                
        except Exception as e:
            self.logger.error("Color change failed", 
                            user=self.username, error=str(e))
            raise
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
