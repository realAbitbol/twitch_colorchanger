# Twitch Color Changer Bot - Functional Documentation

Single authoritative functional specification (merged: removed duplicate updated file).

## Project Overview

The Twitch Color Changer Bot automatically changes a user's Twitch chat color after every message they send. It supports multiple users, random hex colors (Prime/Turbo) and preset Twitch colors (standard), robust token lifecycle management, efficient IRC connectivity, Docker deployment, and structured logging.

## Core Functionality

### Primary Features

1. Automatic Color Changing: Immediate trigger after each own message (no artificial delay)
2. Multi-User Support: Multiple concurrent bot instances in one process
3. Dual Color Modes: Random hex (Prime/Turbo) or preset Twitch colors
4. Smart Turbo/Prime Detection: Automatic fallback to preset colors with persistent settings
5. Color Avoidance: Never repeats the last applied color consecutively
6. Current Color Detection: Initializes from current Twitch color so first change differs
7. Token Management: Forced startup refresh + periodic 10‑minute validation (refresh when <1h remaining or validation fails)
8. IRC Connection: Custom client with JOIN confirmation (numeric 366) + 30s timeout and single retry
9. Docker Support: Multi-architecture image; runs as root for broad NAS / volume compatibility
10. Rate Limiting: Central limiter tracks Helix headers and annotates logs with remaining quota

## Token Lifecycle

Sequence:

1. Startup: Force refresh if refresh token exists (guarantees full validity window; sets `token_expiry`).
2. Every 600s: If `token_expiry` known and < 1 hour → refresh; else validate with `GET /helix/users`; refresh on failure.
3. Persist refreshed tokens (access + possibly new refresh token) back to config file.

Helper-based implementation (`_force_token_refresh`, `_check_expiring_token`, `_validate_token_via_api`, `_attempt_standard_refresh`) reduces complexity.

## Environment vs Config Precedence

- Tokens & client credentials (access, refresh, client_id, client_secret): Config file is source of truth (environment won’t overwrite existing values—safer persistence).
- Runtime fields (channels, use_random_colors): Environment overrides config (explicit env flag wins, including disabling random colors).
- Dual variable support: `TWITCH_USE_RANDOM_COLORS_N` (preferred) and legacy `USE_RANDOM_COLORS_N`.

## Channel Join Reliability

- Each JOIN tracked until RPL_ENDOFNAMES (366) received.
- 30s timeout → one retry (max 2 attempts total) → final failure log if still unconfirmed.
- Only success/failure events logged (no verbose interim “joining” lines).

## Logging Philosophy

Only durable outcomes logged to minimize noise:

- Startup, user_id retrieval, initial color detection
- JOIN success or final failure
- Color change success (with rate limit info) or failure/timeout
- Token expiry status, refresh actions, refresh failures
- Significant warnings (e.g. join timeout, rate limiting)

Example snippet:

```text
🚀 Starting bot for username
✅ username: Retrieved user_id: 12345678
✅ username: Initialized with current color: #00FF7F
✅ username successfully joined #channel1
Color changed to #1e90ff [745/800 reqs]
🔑 username: Token expires in 3.9 hours
⏰ username: Token expires in less than 1 hour, refreshing...
✅ username: Token refreshed and saved successfully
❌ username failed to join #channel2 after 2 attempts (timeout)
```

Transitional log lines like “Changing color to …” are intentionally omitted.

## Color Change Logic

- Random mode: `generate_random_hex_color(exclude_color=last_color)` (HSL distribution; excludes last color)
- Preset mode: `get_different_twitch_color(exclude_color=last_color)` ensures change among named Twitch presets
- 10s timeout wraps `PUT /helix/chat/color`
- On success: updates `last_color`, increments counter, appends rate-limit summary

## Turbo/Prime Error Handling & Fallback

**Automatic Detection**: When a user attempts random hex colors but lacks Turbo/Prime subscription:

1. **Error Detection**: API returns error containing "Turbo or Prime user" or "Hex color code"
2. **Immediate Fallback**: Bot automatically disables random colors for this user
3. **Persistent Configuration**: Setting is saved to config file (`use_random_colors: false`)
4. **Seamless Continuation**: Bot retries with preset Twitch colors without user interruption
5. **Prevention**: Future color changes use preset colors, avoiding repeated API errors

**Workflow Example**:

```text
[WARNING] User username requires Turbo/Prime for hex colors. Disabling random colors and using preset colors.
🔧 Disabled random colors for username (requires Turbo/Prime)
💾 Configuration saved successfully
[INFO] Disabled random colors for username in configuration
[INFO] Color changed to chocolate [799/800 reqs]
```

## Rate Limiting Display

Appends bracketed summary after color change:

- Format examples: `[745/800 reqs]`, `[45/800 reqs, reset in 52s]`, `[⚠️ 3/800 reqs, reset in 12s]`
- Stale or missing header data indicated via placeholders

## Updated Core Methods Overview (bot.py)

- `start()` – startup orchestration (forced refresh, user_id fetch, current color, IRC connect, periodic token task)
- `handle_irc_message()` – processes IRC messages and triggers immediate color changes
- `_check_and_refresh_token()` – coordinator delegating to helper methods
- `_change_color()` – main color change with rate limiting and Turbo/Prime fallback
- `_select_color()` – chooses appropriate color based on user settings and last color
- `_attempt_color_change()` – makes API request and handles response/errors
- `_handle_api_error()` – processes Turbo/Prime errors and disables random colors
- `_try_preset_color_fallback()` – fallback to preset colors when hex colors fail
- `_get_current_color()` – initialization fetch to avoid repeating current color
- `_persist_token_changes()` – saves tokens and settings to config file

## IRC (simple_irc.py) Highlights

- Tracks `pending_joins` with timestamps & attempts
- `_check_join_timeouts()` invoked each loop batch
- Logs only success/failure
- Own PRIVMSG triggers immediate color change scheduling (run loop or thread fallback)

## Security & Deployment

- Container runs as root (simplifies mounted volume permissions, especially NAS)
- Persist only `/app/config` for token continuity
- No UID/GID env indirection supported

## Migration Notes (from earlier versions)

- Remove assumptions about delayed color change (`delayed_color_change()` removed)
- Expect forced token refresh on first run (see startup log)
- Use `TWITCH_USE_RANDOM_COLORS_N=false` to disable random colors even if config sets true
- Remove any legacy UID/GID or non-root adjustments (now unused)

## Future Improvements (Optional Ideas)

- HTTP health/metrics endpoint
- Structured metrics export (Prometheus) for rate limits & token expiry
- Exponential backoff for join retries beyond single second attempt

## Reference & Additional Detail

For deeper architectural breakdown (HTTP pooling, error taxonomy, validator internals), see `IMPLEMENTATION_GUIDE.md` and runtime examples in `README.md`.

---
Canonical functional description last updated after refactor of token management & logging simplification.

## Enhanced Features (2024 Improvements)

### 1. Simple Logging System

**Purpose**: Clean, colored logging for easy monitoring and debugging

**Features**:

- **Environment-Based Configuration**: `DEBUG=true` for debug logging
- **Colored Console Output**: Easy-to-read colored logs for development and production
- **Contextual Information**: User and channel context in log messages
- **Debug Support**: Optional debug-only messages for detailed troubleshooting

**Usage Examples**:

```python
logger.info("Color changed", user="streamername", channel="channelname")
logger.log_api_request("/helix/chat/color", "PUT", user="streamername", response_time=0.245)
```

### 2. Simple Configuration Validation

**Purpose**: Essential validation of configuration parameters with clear error reporting

**Validation Features**:

- **Basic Field Validation**: Required fields (username, access_token, channels)
- **Length Checks**: Username 3-25 characters, token minimum 20 characters
- **Placeholder Detection**: Prevents use of test/placeholder tokens
- **Channel Validation**: Non-empty channel list with valid channel names
- **Duplicate Prevention**: Skips duplicate usernames automatically

**Error Handling**:

- Direct logging of validation errors
- Invalid users are skipped with clear warnings
- Valid users continue processing normally
- Simple boolean validation (pass/fail)

- `_change_color()`: Executes color change via Twitch API (avoids previous color, timeout + rate limit aware)
- `_get_current_color()`: Fetch user's current color from Twitch API for initialization
- `_check_and_refresh_token()`: Orchestrates validation, forced & periodic refresh
- (Removed) `delayed_color_change()`: Color changes are now triggered immediately after own messages for responsiveness

### 3. Simple Error Handling

**Purpose**: Reliable operation with automatic retry and clear error logging

**Exception Types**:

- `APIError`: Twitch API errors with status codes (preserves Turbo/Prime detection)

```text
IRC Message → SimpleTwitchIRC.parse_message() →
TwitchColorBot.handle_irc_message() → _change_color() (immediate) →
Twitch API Call → Success / Failure Logging

**Features**:

- Simple retry mechanism with exponential backoff
- User context logging for debugging
- Preserved Turbo/Prime error detection for automatic fallback

 (No "Changing color to ..." transitional line)
- **Automatic Retries**: Exponential backoff for transient failures
- **Error Tracking**: Frequency monitoring and alerting
- **Contextual Information**: User, channel, API endpoint details
- **Secure Logging**: No sensitive data (tokens) in error messages
**Features**:

- `TWITCH_USE_RANDOM_COLORS_N` / `USE_RANDOM_COLORS_N`: Boolean for hex vs preset colors (default: true). Both supported; prefixed variant preferred.
### 5. Docker Security

- Runs as root (simplified) for broad NAS / volume compatibility
- Minimal base image & least external dependencies
- Only config directory needs persistence

### 6. Enhanced Observability

**Monitoring Capabilities**:

- **API Performance**: Request/response times, status codes, endpoint tracking
- **Rate Limiting**: Current limits, reset times, usage patterns
- **IRC Events**: Connection status, message processing statistics
- **Error Patterns**: Error categories, frequencies, contexts
- **Connection Statistics**: Session age, request count, active connections

### Architecture Components

- Configuration loading and validation

- Bot manager orchestration

- Global error handling and graceful shutdown

**Key Functions:**

- `main()`: Primary application entry point

- Health check mode for Docker deployment validation

#### 2. Configuration Management (`src/config.py`)

- Multi-user configuration handling

- Environment variable processing for Docker

- Configuration file setup

- Token persistence and updates

**Key Functions:**

- `get_docker_config()`: Extract multi-user config from environment variables

- `get_configuration()`: Load configuration from file only

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

- `_change_color()`: Main color change with memory check, rate limiting, and fallback logic

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

- `print_instructions()`: Display setup and usage information

- `print_instructions()`: Display setup and usage information

## Deployment Modes

### 1. Local Development

```bash
# First copy the sample config
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
# Edit with your credentials
python main.py
```

### 2. Docker Single User

```bash
docker run -v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf \
           damastah/twitch-colorchanger
```

### 3. Docker Multi-User

```bash
# Edit twitch_colorchanger.conf to include multiple users
docker run -v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf \
           damastah/twitch-colorchanger
```

### 4. Docker Compose

```yaml
services:
  twitch-colorchanger:
    image: damastah/twitch-colorchanger:latest
    volumes:
      - ./twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf
    restart: unless-stopped
```

### 5. Docker Runtime Permissions

The container now always runs as root for simplicity and broad compatibility (including restrictive NAS mounts). Only the configuration directory is persisted via a volume. No UID/GID remapping or fallback environment variables are supported anymore.

Recommended run:

```bash
docker run -v ./config:/app/config damastah/twitch-colorchanger:latest
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
TwitchColorBot.handle_irc_message() → _change_color() → API request
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

- Low memory footprint (~30-40MB per bot instance)

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

- `aiohttp>=3.9.0`: Async HTTP client for optimal performance

### System Requirements

- Python 3.13+ (uses latest asyncio features)

- Network connectivity to twitch.tv and irc.chat.twitch.tv

- Write permissions for configuration persistence

### Docker Requirements

- Multi-architecture support (amd64, arm64, arm/v7, riscv64)

- Alpine Linux base for minimal size

- Volume mounting capability for persistence

## Configuration Reference

### Environment Variables

Environment variables:

- `DEBUG`: Enable debug logging (default: false)

### Configuration File

All bot configuration is done via the `twitch_colorchanger.conf` file. Use the sample file as a template:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
```

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
4. **Color changes failing**: Verify token scopes and Prime/Turbo status for hex colors

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
