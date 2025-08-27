# Twitch Color Changer Bot - Functional Documentation

## Project Overview

The Twitch Color Changer Bot is a Python-based application that automatically changes Twitch username colors after each message sent by configured users. It supports multiple users, both random hex colors (for Prime/Turbo users) and preset Twitch colors, and includes comprehensive token management with automatic refresh capabilities.

## Core Functionality

### Primary Features

1. **Automatic Color Changing**: Changes username color after each message sent
2. **Multi-User Support**: Runs multiple bot instances simultaneously for different users
3. **Dual Color Modes**: Random hex colors for Prime/Turbo users, preset colors for regular users
4. **Color Avoidance**: Ensures each color change is different from the previous one
5. **Current Color Detection**: Initializes with user's current color to guarantee first change is different
6. **Token Management**: Automatic token refresh with 10-minute validation intervals
7. **IRC Connection**: Custom IRC implementation for reliable Twitch chat monitoring
8. **Docker Support**: Containerized deployment with multi-architecture support

## Enhanced Features (2024 Improvements)

### 1. Structured Logging System

**Purpose**: Enterprise-grade logging with JSON output and contextual information

**Features**:

- **Environment-Based Configuration**: `DEBUG=true` for debug logging, `LOG_FORMAT=json` for structured output
- **Multiple Output Formats**: Colored console logs for development, JSON logs for production
- **Contextual Information**: User, channel, API endpoint, response time tracking
- **Specialized Methods**: API request logging, rate limit monitoring, IRC event tracking
- **File Logging**: Optional file output with `LOG_FILE` environment variable

**Usage Examples**:

```python
logger.info("Color changed", user="streamername", channel="channelname")
logger.log_api_request("/helix/chat/color", "PUT", user="streamername", response_time=0.245)
```

### 2. Enhanced Configuration Validation

**Purpose**: Comprehensive validation of all configuration parameters with detailed error reporting

**Validation Categories**:

- **Format Validation**: Regex patterns for usernames (3-25 chars), tokens, client credentials
- **Security Checks**: Detects placeholder tokens, validates token formats
- **Conflict Detection**: Duplicate usernames, overlapping channels
- **Recommendations**: Optimization suggestions for configuration

**Error Reporting**:

- Errors: Critical issues preventing operation
- Warnings: Non-critical issues that should be addressed
- Info: Optimization recommendations

### 3. Advanced Error Handling

**Purpose**: Resilient operation with automatic recovery and detailed error categorization

**Exception Types**:

- `NetworkError`: Connection and HTTP-related failures
- `AuthenticationError`: Token validation and refresh issues
- `APIError`: Twitch API-specific errors with endpoint context
- `RateLimitError`: Rate limiting with automatic retry timing
- `ConfigurationError`: Configuration validation failures
- `IRCError`: IRC connection and message processing errors

**Features**:

- **Automatic Retries**: Exponential backoff for transient failures
- **Error Tracking**: Frequency monitoring and alerting
- **Contextual Information**: User, channel, API endpoint details
- **Secure Logging**: No sensitive data (tokens) in error messages

### 4. HTTP Connection Pooling

**Purpose**: Optimized HTTP performance with resource management and memory leak prevention

**Features**:

- **Connection Reuse**: Keep-alive connections reduce handshake overhead
- **Resource Limits**: 50 total connections, 10 per host
- **Automatic Cleanup**: Proper session lifecycle management
- **DNS Caching**: Improved performance for repeated requests
- **Compression**: Automatic response decompression
- **Memory Leak Prevention**: Cross-loop session cleanup, reference nullification

**Performance Benefits**:

- Reduced latency through connection reuse
- Better throughput with concurrent request handling
- Efficient resource usage with automatic cleanup

### 5. Memory Monitoring

**Purpose**: Detection and prevention of memory leaks in long-running bot instances

**Features**:

- **Periodic Leak Detection**: Automatic checks every 5 minutes during operation
- **Baseline Comparison**: Compares current memory usage to startup baseline
- **Object Tracking**: Monitors HTTP-related objects for increases
- **Cross-Loop Safety**: Proper cleanup of sessions across different event loops

### 6. Enhanced Observability

**Monitoring Capabilities**:

- **API Performance**: Request/response times, status codes, endpoint tracking
- **Rate Limiting**: Current limits, reset times, usage patterns
- **IRC Events**: Connection status, message processing statistics
- **Error Patterns**: Error categories, frequencies, contexts
- **Connection Statistics**: Session age, request count, active connections

### Architecture Components

#### 1. Main Entry Point (`main.py`)

- Application bootstrap and initialization

- Configuration loading and validation

- Bot manager orchestration

- Global error handling and graceful shutdown

**Key Functions:**

- `main()`: Primary application entry point

- Health check mode for Docker deployment validation

#### 2. Configuration Management (`src/config.py`)

- Multi-user configuration handling

- Environment variable processing for Docker

- Interactive configuration setup

- Token persistence and updates

**Key Functions:**

- `get_docker_config()`: Extract multi-user config from environment variables

- `get_interactive_config()`: Interactive setup for local deployment

- `load_users_from_config()` / `save_users_to_config()`: JSON config file management

- `update_user_in_config()`: Update specific user tokens after refresh

**Configuration Format:**

```json
{
  "users": [
    {
      "username": "user1",
      "access_token": "token1",
      "refresh_token": "refresh1", 
      "client_id": "id1",
      "client_secret": "secret1",
      "channels": ["channel1", "channel2"],
      "use_random_colors": true
    }
  ]
}
```

#### 3. Bot Manager (`src/bot_manager.py`)

- Multi-bot orchestration and lifecycle management

- Task creation and monitoring

- Error handling and recovery

- Graceful shutdown coordination

**Key Classes:**

- `BotManager`: Manages multiple TwitchColorBot instances

- Methods: `start_all_bots()`, `create_bot()`, `wait_for_completion()`, `stop_all_bots()`

#### 4. Core Bot Logic (`src/bot.py`)

- Individual bot implementation

- Twitch API integration

- IRC message handling

- Token refresh automation

**Key Class: `TwitchColorBot`**

**Core Methods:**

- `start()`: Initialize bot, connect to IRC, start background tasks, fetch current color

- `handle_irc_message()`: Process incoming chat messages and trigger color changes

- `change_color()`: Execute color change via Twitch API (avoids previous color)

- `get_current_color()`: Fetch user's current color from Twitch API for initialization

- `check_and_refresh_token()`: Validate and refresh authentication tokens

- `delayed_color_change()`: Add random delay (1-3s) before color change

**Token Management:**

- Periodic validation every 10 minutes

- Automatic refresh when expiry < 1 hour

- Persistent storage of updated tokens

- Username logging for token status

**API Integration:**

- Uses Twitch Helix API for color changes and user info

- Proper HTTP status validation (204 = success)

- URL encoding for hex colors (#RRGGBB → %23RRGGBB)

- Error handling and retry logic

#### 5. IRC Client (`src/simple_irc.py`)

- Custom IRC implementation replacing broken TwitchIO

- Raw socket-based connection to irc.chat.twitch.tv:6667

- Message parsing and event handling

- Debug-aware message display

**Key Class: `SimpleTwitchIRC`**

**Core Methods:**

- `connect()`: Establish IRC connection with OAuth authentication

- `join_channel()`: Join specified Twitch channels

- `listen()`: Main message processing loop

- `parse_message()`: Parse raw IRC messages into structured data

- `set_message_handler()`: Set callback for message events

**Message Handling:**

- Processes PRIVMSG commands for chat messages

- Handles PING/PONG keepalive

- Filters display based on debug mode and message sender

- Calls bot's message handler for own messages only

#### 6. Color System (`src/colors.py`)

- Color generation and management

- Console output formatting

- Twitch color presets

**Functions:**

- `generate_random_hex_color()`: Creates random hex colors using HSL color space

- `get_twitch_colors()`: Returns list of preset Twitch colors

- `bcolors`: ANSI color codes for console output

**Color Generation Algorithm:**

```python

# HSL-based generation for better color distribution

hue = random.randint(0, 359)        # Full hue range

saturation = random.randint(60, 100) # High saturation

lightness = random.randint(35, 75)   # Moderate lightness

# Convert to RGB and format as hex

```

#### 7. Utilities (`src/utils.py`)

- Logging with debug mode support

- User input handling

- Channel name processing

- Setup instructions display

**Key Functions:**

- `print_log()`: Debug-aware logging with color support

- `process_channels()`: Parse comma-separated channel lists

- `prompt_for_user()`: Interactive user credential collection

- `print_instructions()`: Display setup and usage information

## Deployment Modes

### 1. Local Development

```bash
python main.py

# Interactive configuration prompts

# Saves config to twitch_colorchanger.conf

```

### 2. Docker Single User

```bash
docker run -e TWITCH_USERNAME=user \
           -e TWITCH_ACCESS_TOKEN=token \
           -e TWITCH_REFRESH_TOKEN=refresh \
           -e TWITCH_CLIENT_ID=id \
           -e TWITCH_CLIENT_SECRET=secret \
           damastah/twitch-colorchanger

```

### 3. Docker Multi-User

```bash
docker run -e TWITCH_USERNAME_1=user1 \

           -e TWITCH_ACCESS_TOKEN_1=token1 \

           -e TWITCH_USERNAME_2=user2 \

           -e TWITCH_ACCESS_TOKEN_2=token2 \

           # ... additional users with _N suffix

           damastah/twitch-colorchanger

```

### 4. Docker Compose

```yaml
services:
  twitch-colorchanger:
    image: damastah/twitch-colorchanger:latest
    environment:
      - TWITCH_USERNAME_1=user1

      - TWITCH_ACCESS_TOKEN_1=token1

      # ... additional configuration

    volumes:
      - ./config:/app/config

    restart: unless-stopped

```

## API Integration

### Twitch Helix API Endpoints

1. **Color Change**: `PUT /helix/chat/color`
   - Parameters: `user_id`, `color` (hex or preset name)

   - Success: HTTP 204 (No Content)

   - Authentication: Bearer token + Client-ID header

2. **User Info**: `GET /helix/users`
   - Response: User data including user_id

   - Used for user_id resolution and token validation

3. **Token Refresh**: `POST /oauth2/token`
   - Grant type: refresh_token

   - Response: New access_token and optional refresh_token

### IRC Protocol Implementation

- **Server**: irc.chat.twitch.tv:6667

- **Authentication**: OAuth PASS/NICK sequence

- **Capabilities**: membership, tags, commands

- **Message Format**: Standard IRC PRIVMSG parsing

- **Keepalive**: PING/PONG handling

## Data Flow

### 1. Startup Sequence

```text
main.py → Configuration Loading → Bot Manager → Individual Bots
```

### 2. Message Processing Flow

```text

IRC Message → SimpleTwitchIRC.parse_message() → 
TwitchColorBot.handle_irc_message() → delayed_color_change() → 
Twitch API Call → Success/Error Logging

```

### 3. Token Management Flow

```text

Periodic Check (10 min) → Token Validation → 

Refresh if Needed → Update Config → Continue Operation

```

## Error Handling

### Network Errors

- IRC connection failures with reconnection attempts

- HTTP timeouts with aiohttp ClientTimeout

- API rate limiting handling

### Authentication Errors

- Invalid token detection and refresh

- OAuth scope validation

- Client credential verification

### Configuration Errors

- Missing required fields validation

- Invalid JSON format handling

- Environment variable validation

## Security Features

### Docker Security

- Non-root user execution (appuser:1001)

- Minimal Alpine Linux base image

- No unnecessary packages or permissions

- Volume mounting for config persistence only

### Token Security

- Tokens stored in configuration files or environment variables

- No token logging in production mode

- Automatic token refresh prevents long-lived credentials

- Refresh tokens used instead of password authentication

### Network Security

- HTTPS for all API calls

- SSL-capable IRC connection option

- No unnecessary network exposure

## Performance Characteristics

### Resource Usage

- Minimal CPU usage (event-driven architecture)

- Low memory footprint (~50MB per bot instance)

- Efficient asyncio-based concurrent operation

- No polling - pure event-driven message processing

### Scalability

- Horizontal scaling via multiple container instances

- Multi-user support within single instance

- Independent bot lifecycles

- Configurable delay randomization to avoid API rate limits

## Logging and Monitoring

### Log Levels

- **Debug Mode**: Detailed IRC traffic, API calls, internal state

- **Normal Mode**: Status updates, errors, user actions only

- **Production**: Minimal logging with focus on errors and health

### Health Monitoring

- Docker health check endpoint

- Bot status tracking

- Token expiry monitoring

- IRC connection status

### Log Format

```text

🚀 Starting bot for username
🎨 username: Changing color to #RRGGBB  
✅ username: Color changed to #RRGGBB
🔑 username: Token expires in X.X hours
❌ Error messages with context

```

## Dependencies

### Core Python Packages

- `aiohttp>=3.9.0`: Async HTTP client for Twitch API

- `requests>=2.31.0`: Fallback HTTP client

### System Requirements

- Python 3.13+ (uses latest asyncio features)

- Network connectivity to twitch.tv and irc.chat.twitch.tv

- Write permissions for configuration persistence

### Docker Requirements

- Multi-architecture support (amd64, arm64, arm/v7, riscv64)

- Alpine Linux base for minimal size

- Volume mounting capability for persistence

## Configuration Reference

### Required Environment Variables (Per User)

- `TWITCH_USERNAME_N`: Twitch username

- `TWITCH_ACCESS_TOKEN_N`: OAuth access token

- `TWITCH_REFRESH_TOKEN_N`: OAuth refresh token

- `TWITCH_CLIENT_ID_N`: Twitch application client ID

- `TWITCH_CLIENT_SECRET_N`: Twitch application client secret

### Optional Environment Variables (Per User)

- `TWITCH_CHANNELS_N`: Comma-separated channel list (default: username)

- `USE_RANDOM_COLORS_N`: Boolean for hex vs preset colors (default: true)

### Global Environment Variables

- `DEBUG`: Enable debug logging (default: false)

- `FORCE_COLOR`: Enable ANSI colors (default: true)

- `TWITCH_CONF_FILE`: Configuration file path (default: twitch_colorchanger.conf)

### Twitch API Setup Requirements

1. Create application at [https://dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps)
2. Set redirect URL to [https://twitchtokengenerator.com](https://twitchtokengenerator.com)
3. Generate tokens at [https://twitchtokengenerator.com](https://twitchtokengenerator.com)
4. Required scopes: `chat:read`, `user:manage:chat_color`

## Troubleshooting Guide

### Common Issues

1. **Bot not detecting messages**: Check IRC connection and channel joins
2. **Color changes failing**: Verify token scopes and Prime/Turbo status for hex colors
3. **Token expired**: Refresh tokens automatically, check client credentials
4. **Multi-user conflicts**: Ensure unique numbered environment variables

### Debug Mode Activation

```bash

# Local

DEBUG=true python main.py

# Docker

docker run -e DEBUG=true damastah/twitch-colorchanger

```

### Log Analysis

- Green ✅: Successful operations

- Red ❌: Errors requiring attention

- Yellow ⚠️: Warnings that may indicate issues

- Blue 🔵: Informational status updates

This documentation provides complete specifications for recreating the Twitch Color Changer Bot, including all functionality, architecture decisions, deployment methods, and operational considerations.
