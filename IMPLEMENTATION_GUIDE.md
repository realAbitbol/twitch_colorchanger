# Twitch Color Changer Bot - Implementation Guide

This guide provides the essential architectural patterns and implementation details needed to recreate the Twitch Color Changer Bot based on the actual codebase structure.

## Project Architecture

### Directory Structure

```text
twitch_colorchanger/
├── main.py                     # Application entry point
├── requirements.txt            # Dependencies (aiohttp, watchdog)
├── Dockerfile                  # Multi-platform container
├── docker-compose.yml-sample   # Deployment template
├── twitch_colorchanger.conf    # Runtime configuration (JSON)
└── src/
    ├── __init__.py
    ├── bot.py                  # Core bot implementation
    ├── bot_manager.py          # Multi-bot orchestration
    ├── colors.py               # Color generation and management
    ├── config.py               # Configuration management
    ├── config_validator.py     # Configuration validation
    ├── config_watcher.py       # Live config reload
    ├── device_flow.py          # OAuth Device Authorization Grant
    ├── error_handling.py       # Exception handling
    ├── logger.py               # Structured logging
    ├── rate_limiter.py         # API rate limiting
    ├── simple_irc.py           # IRC client implementation
    ├── utils.py                # Utility functions
    └── watcher_globals.py      # Global watcher coordination
```

### Core Dependencies

```text
aiohttp>=3.9.0,<4.0.0    # HTTP client for Twitch API
watchdog>=3.0.0,<4.0.0   # File system monitoring
```

## Implementation Components

### 1. Application Entry Point (`main.py`)

**Architecture Pattern**: Simple async main with error handling

- **Configuration Loading**: `get_configuration()` loads users from JSON config
- **Automatic Token Setup**: `setup_missing_tokens()` handles device flow for missing/invalid tokens
- **Bot Orchestration**: `run_bots(users_config, config_file)` manages all bot instances
- **Health Check Mode**: `--health-check` flag for Docker health checks
- **Graceful Shutdown**: Keyboard interrupt and exception handling

### 2. Core Bot Implementation (`src/bot.py`)

**Architecture Pattern**: Event-driven async bot with state management

**Key Classes**:

- `TwitchColorBot`: Main bot class handling individual user

**Core Methods**:

- `start()`: Initialization, token refresh, IRC connection, background tasks
- `handle_irc_message()`: Processes IRC messages and triggers color changes
- `_change_color()`: Main color change logic with API calls
- `_check_and_refresh_token()`: Token validation and refresh coordination
- `_get_current_color()`: Fetches current color to avoid repetition

**State Management**:

- Current color tracking to avoid consecutive repeats
- Token expiry tracking for proactive refresh
- Turbo/Prime status with persistent fallback settings

### 3. Multi-Bot Manager (`src/bot_manager.py`)

**Architecture Pattern**: Async task orchestration with health monitoring

**Key Class**: `BotManager`

- **Bot Lifecycle**: Start, monitor, restart on config changes, graceful shutdown
- **Task Management**: Creates async tasks for each bot instance
- **Config Watcher Integration**: Sets up file watching on startup
- **Signal Handling**: Proper cleanup on SIGTERM/SIGINT

**Core Methods**:

- `_start_all_bots()`: Creates and starts bot instances
- `_create_bot()`: Factory method for individual bots
- `_stop_all_bots()`: Coordinated shutdown of all bots
- `_save_statistics()`: Preserves bot statistics before restart
- `_restore_statistics()`: Restores statistics to new bot instances

### 4. Configuration System (`src/config.py`)

**Architecture Pattern**: JSON-based config with environment override

**Configuration Format**: Multi-user JSON structure

```json
{
  "users": [{
    "username": "string",
    "access_token": "string", 
    "refresh_token": "string",
    "client_id": "string",
    "client_secret": "string",
    "channels": ["array"],
    "is_prime_or_turbo": boolean
  }]
}
```

**Key Functions**:

- `get_configuration()`: Loads from file only (no environment)
- `get_docker_config()`: Extracts config from environment variables
- `update_user_in_config()`: Updates specific user after token refresh
- `setup_missing_tokens()`: Automatic token setup via device flow integration

### 5. Device Flow Token Setup (`src/device_flow.py`)

**Architecture Pattern**: OAuth Device Authorization Grant implementation

**Key Class**: `DeviceCodeFlow`

- **Device Code Request**: Generates device code and user verification URL
- **Unattended Polling**: Automated polling for authorization completion
- **User Interface**: Clear instructions with expiry tracking
- **Error Handling**: Handles authorization denial, timeouts, and rate limiting

**Core Methods**:

- `request_device_code()`: Requests device code from Twitch OAuth endpoint
- `poll_for_tokens()`: Polls for authorization completion with exponential backoff
- `get_user_tokens()`: Complete flow returning access/refresh tokens
- `_handle_polling_error()`: Processes various OAuth error responses

**Integration Points**:

- Called by `setup_missing_tokens()` when existing tokens are invalid
- Automatically triggered on bot startup for users without valid tokens
- Results saved to configuration file for future use

### 6. Live Configuration Reload (`src/config_watcher.py`)

**Architecture Pattern**: File system event handling with coordination

**Key Classes**:

- `ConfigFileHandler(FileSystemEventHandler)`: Handles file modification events
- `ConfigWatcher`: Manages Observer lifecycle and coordinates restarts

**Coordination System** (`src/watcher_globals.py`):

- Global watcher instance management
- `pause_config_watcher()` / `resume_config_watcher()` functions
- Prevents bot-triggered infinite restart loops

**Implementation Details**:

- 1-second debouncing for rapid file changes
- Thread-safe pause/resume mechanism
- Config validation before triggering restart
- Bot-aware updates pause watcher during config saves
- Statistics preservation across bot restarts

### 6. IRC Client (`src/simple_irc.py`)

**Architecture Pattern**: Raw socket IRC client with async message handling

**Key Class**: `SimpleTwitchIRC`

- **Connection Management**: Raw socket to irc.chat.twitch.tv:6667
- **Authentication**: OAuth token-based IRC authentication
- **Message Parsing**: Custom IRC message parser for PRIVMSG events
- **Event Handling**: Callback-based message processing

**Reliability Features**:

- JOIN confirmation waiting (numeric 366)
- PING/PONG keepalive handling
- Connection timeout with retry logic
- Debug-aware message filtering

### 7. API Integration Patterns

**HTTP Client Pattern**: Direct aiohttp usage

- **Function**: `_make_api_request()` handles all Twitch API calls
- **Headers**: Bearer token + Client-ID authentication
- **Error Handling**: Status code and JSON response parsing
- **Rate Limiting**: Integration with centralized rate limiter

**API Endpoints**:

- `PUT /helix/chat/color`: Color changes (returns 204)
- `GET /helix/users`: User info and token validation
- `POST /oauth2/token`: Token refresh operations

### 8. Rate Limiting (`src/rate_limiter.py`)

**Architecture Pattern**: Global rate limiter with quota tracking

- **Implementation**: Token bucket with async acquire()
- **Header Parsing**: Extracts rate limit info from Twitch responses
- **Quota Logging**: Tracks and logs remaining API quota
- **Global Instance**: `get_rate_limiter()` returns singleton

### 9. Color Management (`src/colors.py`)

**Architecture Pattern**: Utility functions for color generation

**Color Types**:

- Random hex colors: `generate_random_hex_color()`
- Preset Twitch colors: `get_different_twitch_color(current_color)`
- Color avoidance: Ensures no consecutive repeats

**Fallback Logic**:

- Automatic detection of non-Turbo/Prime users
- Persistent fallback to preset colors
- Configuration updates for fallback mode

### 10. Logging System (`src/logger.py`)

**Architecture Pattern**: Structured logging with context

**Features**:

- Colored console output using `bcolors` class
- Contextual logging with user/channel information
- Debug mode support via environment variables
- API request logging with performance metrics

### 11. Error Handling (`src/error_handling.py`)

**Architecture Pattern**: Centralized exception handling

**Exception Types**:

- `APIError`: Twitch API errors with status codes
- Generic error handling with context preservation
- `simple_retry()`: Exponential backoff retry mechanism

**Error Context**:

- User and operation context in error logs
- No sensitive data (tokens) in error messages
- Graceful degradation on failures

### 12. Configuration Validation (`src/config_validator.py`)

**Architecture Pattern**: Comprehensive validation with detailed reporting

**Validation Rules**:

- Required field presence (username, tokens, channels, credentials)
- Format validation (token length, username format)
- Placeholder detection (prevents example values)
- Channel name validation

**Error Handling**:

- Field-specific error messages
- Invalid users skipped with warnings
- Graceful continuation with valid users

## Key Implementation Patterns

### Async Programming

- **Event-driven Architecture**: All I/O operations are async
- **Task Management**: asyncio.create_task() for concurrent operations
- **Context Management**: Proper resource cleanup with try/finally blocks

### State Management

- **Immutable Configuration**: Config reloaded on changes
- **Persistent State**: Token updates saved to config file
- **Memory State**: Current color and status tracking per bot

### Error Recovery

- **Exponential Backoff**: Intelligent retry with increasing delays
- **Circuit Breaker Pattern**: Fallback to preset colors on repeated failures
- **Graceful Degradation**: Continue operation with reduced functionality

### Resource Management

- **Connection Pooling**: Efficient HTTP client usage
- **Memory Efficiency**: Minimal state per bot instance
- **Clean Shutdown**: Proper resource cleanup on termination

## Docker Implementation

### Container Architecture

- **Base Image**: Alpine Linux for minimal size
- **Multi-platform**: Supports amd64, arm64, arm/v7, arm/v6, riscv64
- **Health Checks**: Built-in endpoint for container orchestration
- **Volume Mapping**: Config directory persistence

### Deployment Pattern

- **Environment Configuration**: Full config via environment variables
- **File Configuration**: JSON config file with volume mount
- **Signal Handling**: Proper container shutdown behavior

## Testing Strategy

### Integration Testing

- **Config Watching**: User changes trigger restart, bot changes don't
- **Token Refresh**: Validates token lifecycle management
- **Multi-user**: Ensures independent bot operation

### Error Simulation

- **API Failures**: Tests fallback and retry mechanisms
- **Network Issues**: Validates connection recovery
- **Invalid Config**: Tests validation and error handling

## Security Considerations

### Token Management

- **Secure Storage**: Tokens in config files, not environment logs
- **Automatic Refresh**: Minimizes token exposure time
- **No Logging**: Prevents token leakage in debug output

### Network Security

- **HTTPS Only**: All API calls use secure connections
- **Authentication**: Proper OAuth token handling
- **Rate Limiting**: Prevents API abuse

This implementation guide reflects the actual architecture and patterns used in the current Twitch Color Changer Bot codebase.
