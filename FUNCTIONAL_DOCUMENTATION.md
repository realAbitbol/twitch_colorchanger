# Twitch Color Changer Bot - Functional Documentation

This document describes the functional capabilities and behavior of the Twitch Color Changer Bot as implemented in the current codebase.

## Project Overview

The Twitch Color Changer Bot automatically changes a user's Twitch chat color after every message they send. It supports multiple users simultaneously, both random hex colors (Prime/Turbo users) and preset Twitch colors (standard users), robust token lifecycle management, efficient IRC connectivity, Docker deployment, and live configuration reload.

## Core Functionality

### Primary Features

1. **Automatic Color Changing**: Immediate color change triggered after each user's own message
2. **Multi-User Support**: Multiple concurrent bot instances running in one process
3. **Dual Color Modes**: Random hex colors (#RRGGBB) for Prime/Turbo users, preset Twitch colors for standard users
4. **Smart Turbo/Prime Detection**: Automatic fallback to preset colors when hex colors fail, with persistent settings
5. **Color Avoidance**: Never repeats the same color consecutively
6. **Current Color Detection**: Fetches current Twitch color on startup to ensure first change is different
7. **Token Management**: Automatic token refresh with proactive expiry checking (600-second intervals)
8. **IRC Connection**: Custom IRC client with health monitoring and automatic reconnection
9. **Docker Support**: Multi-architecture container images with simplified deployment
10. **Live Configuration Reload**: Automatic bot restart when config file changes externally
11. **Channel Deduplication**: Automatically removes duplicate channels and persists clean configuration
12. **Connection Health Monitoring**: 600-second ping intervals with 300-second activity timeouts
13. **Visible Connection Status**: Real-time ping/pong logging for transparency
14. **Per-User Runtime Toggle**: Enable or disable automatic color changes at runtime via chat commands (`ccd` / `cce`) with persisted state

### Color Change Flow

```text
User sends message → IRC client receives → Bot detects own message →
Generate new color (avoiding current) → API call to Twitch → Color changed →
Statistics updated
```

### IRC Connection Management

- **Health Monitoring**: Tracks server activity with 300-second timeout
- **Ping Intervals**: Expects server pings every 600 seconds
- **Automatic Reconnection**: Force reconnects on stale connections
- **Visible Status**: Real-time ping/pong messages with username identification
- **Channel Join Management**: 30-second timeouts with retry logic (max 2 attempts)
- **Multi-Channel Support**: Joins multiple channels with confirmation tracking

### Runtime Chat Commands

Provides in-chat, per-user control of the automatic color cycling feature. Commands are only acted upon when sent by the bot's own authenticated user (messages from other users are ignored).

| Command | Effect |
|---------|--------|
| `ccd`   | Disable automatic color changes for that user (writes `"enabled": false` to config) |
| `cce`   | Enable automatic color changes for that user (writes `"enabled": true` to config)  |

Behavior Characteristics:

- State persists across restarts (stored in configuration file)
- Default is enabled (`true`) if the field is absent (backwards compatible)
- Disabling suppresses outbound Twitch color API calls but keeps IRC connection, statistics, and token tasks active
- Changes are logged through structured events (`auto_color_disabled`, `auto_color_enabled`)
- Commands never affect other configured users

## Token Lifecycle Management

### Automatic Token Setup

- **Device Flow Integration**: Uses OAuth Device Authorization Grant for automatic token generation
- **Missing Token Detection**: Automatically detects users without valid tokens on startup
- **Unattended Authorization**: User authorizes once via browser, bot handles all polling and token retrieval
- **Smart Fallback**: Only triggers device flow when existing tokens are invalid or can't be refreshed
- **Config Integration**: Automatically saves new tokens to configuration file

### Device Flow Process

```text
Bot startup → Check token validity → If invalid/missing → Generate device code →
Display authorization URL + code → User authorizes in browser →
Bot polls for completion → Receives tokens → Saves to config → Continues startup
```

### Startup Behavior

- **Token Validation**: Checks existing tokens first before triggering device flow
- **Force Refresh**: Attempts token refresh at startup to ensure fresh 4-hour window
- **Device Flow Fallback**: Only used when validation and refresh both fail
- **Config Persistence**: Automatically updates config with new tokens
- **User ID Retrieval**: Fetches user ID from Twitch API for operations
- **Current Color Detection**: Retrieves current color to avoid immediate repetition
- **Channel Deduplication**: Removes duplicate channels and persists clean configuration
- **IRC Connection**: Establishes connection and joins all configured channels

### Periodic Maintenance

- **600-Second Checks**: Validates tokens every 600 seconds (10 minutes)
- **Proactive Refresh**: Refreshes when <1 hour remaining
- **Force Refresh at Startup**: Ensures fresh 4-hour token window on bot start
- **Fallback Validation**: API validation if expiry time unknown
- **Config Persistence**: Updates config file with new tokens

### Error Handling

- **Automatic Retry**: Exponential backoff for temporary failures
- **Token Invalidation**: Handles revoked or expired tokens gracefully
- **Device Flow Recovery**: Falls back to device flow for completely invalid tokens
- **Fallback Strategy**: Continues operation with available valid tokens

## Configuration System

### Multi-User Configuration Format

```json
{
  "users": [
    {
      "username": "streamername",
      "access_token": "oauth_token",
      "refresh_token": "refresh_token",
      "client_id": "twitch_client_id",
      "client_secret": "client_secret",
  "channels": ["channel1", "channel2"],
  "is_prime_or_turbo": true,
  "enabled": true
    }
  ]
}
```

#### Enabled Flag (`enabled`)

Optional per-user boolean controlling whether automatic color changes are performed.

Key points:

- If omitted, defaults to `true` (maintains behavior for legacy configs)
- When set to `false`, the bot still connects, watches IRC, refreshes tokens, and gathers statistics but skips color change requests
- Modified at runtime by chat commands `ccd` (disable) and `cce` (enable)
- Persisted immediately (asynchronously) to configuration upon change to survive restarts

Use cases: temporarily pause during events, testing sessions, reducing API usage, or diagnosing issues without removing the user entry.

### Environment Variable Support

- **Docker Integration**: Environment variables override config file settings
- **Runtime Configuration**: Channels and color preferences from environment
- **Token Persistence**: Tokens always saved to config file for persistence

### Live Configuration Reload

- **File Watching**: Monitors config file for external changes using watchdog
- **Validation**: Validates new configuration before applying
- **Bot Coordination**: Prevents infinite restart loops from bot-initiated config updates
- **Debouncing**: 1-second delay prevents multiple rapid restarts
- **Statistics Persistence**: Preserves bot statistics (messages sent, colors changed) across config restarts

### Configuration Validation and Processing

- **Legacy Format Support**: Supports both multi-user and legacy single-user formats
- **User Validation**: Comprehensive validation with detailed error reporting
- **Graceful Handling**: Invalid users are skipped with warnings, valid users continue
- **Automatic Conversion**: Legacy single-user configs automatically converted to multi-user format

## Multi-Bot Orchestration

### Application Entry Point

- **Main Function**: Handles startup flow, configuration loading, and token setup
- **Health Check Mode**: `--health-check` flag for Docker health verification
- **Welcome Instructions**: Displays setup guidance on first run
- **Environment Variables**: Supports `TWITCH_CONF_FILE` for custom config paths
- **Signal Handling**: Proper graceful shutdown on interruption

### Bot Manager Architecture

- **Independent Bots**: Each user runs as separate bot instance
- **Concurrent Execution**: All bots run simultaneously using asyncio
- **Health Monitoring**: Tracks bot status and handles failures
- **Graceful Shutdown**: Coordinated shutdown of all bots
- **Statistics Persistence**: Maintains bot statistics across configuration restarts

### Resource Management

- **Task Management**: Each bot runs as async task
- **Error Isolation**: Bot failures don't affect other bots
- **Memory Efficiency**: Shared resources where possible
- **Signal Handling**: Proper cleanup on termination signals

## IRC Implementation

### Connection Management

- **Server**: irc.chat.twitch.tv:6667 with 10-second connection timeout
- **Authentication**: OAuth token-based authentication with Twitch capabilities
- **Capabilities**: Membership, tags, and commands capabilities
- **Health Monitoring**: 300-second activity timeout, 600-second ping interval expectation
- **Automatic Reconnection**: Force reconnection on stale connections with state preservation
- **Visible Status**: Real-time ping/pong logging with username identification

### Message Processing

- **Real-time Processing**: Event-driven message handling with activity timestamp tracking
- **Own Message Detection**: Only processes messages from the bot's own username
- **Channel Management**: Supports multiple channels with join confirmation tracking
- **Channel Joining**: 30-second timeout with retry logic (maximum 2 attempts)
- **Debug Support**: Optional verbose message logging for development
- **Message Truncation**: Displays first 50 characters of messages in logs

### Health Monitoring

- **Server Activity Tracking**: Monitors any server communication (5-minute timeout)
- **Ping Interval Monitoring**: Expects Twitch server pings every 600 seconds
- **Connection Health Checks**: Periodic validation during message processing
- **Automatic Recovery**: Force reconnection when connection appears stale
- **State Preservation**: Maintains channel memberships across reconnections

### Reliability Features

- **Join Confirmation**: Waits for numeric 366 confirmation
- **Connection Timeout**: 30-second timeout with retry logic
- **Error Recovery**: Automatic reconnection on failures

## API Integration

### Twitch Helix API Endpoints

1. **Color Change**: `PUT /helix/chat/color`
   - Sets user chat color (hex or preset)
   - Returns 204 on success
   - Rate limited by Twitch

2. **User Information**: `GET /helix/users`
   - Retrieves user ID and current color
   - Used for token validation
   - Required for color change operations

3. **Token Refresh**: `POST /oauth2/token`
   - Refreshes expired access tokens
   - Returns new access and refresh tokens
   - Critical for long-running operation

### Rate Limiting

- **Global Rate Limiter**: Centralized rate limiting across all bots
- **Quota Tracking**: Monitors API usage and remaining quota
- **Intelligent Backoff**: Respects Twitch rate limit headers
- **Usage Logging**: Logs rate limit status for monitoring

## Error Handling Strategy

### Exception Categories

- **API Errors**: Twitch API failures with status codes
- **Network Errors**: Connection and timeout issues
- **Configuration Errors**: Invalid config or missing tokens
- **IRC Errors**: Connection and protocol issues

### Recovery Mechanisms

- **Exponential Backoff**: Intelligent retry with increasing delays
- **Graceful Degradation**: Continues operation with partial functionality
- **Error Logging**: Detailed error context without exposing sensitive data
- **User Notification**: Clear error messages for troubleshooting

### Turbo/Prime Detection

- **Automatic Fallback**: Detects non-Turbo/Prime users from API errors
- **Persistent Settings**: Saves fallback mode to config
- **Transparent Operation**: Seamlessly switches to preset colors

## Deployment Architecture

### Docker Support

- **Multi-platform Images**: amd64, arm64, arm/v7, arm/v6, riscv64
- **Minimal Base**: Alpine Linux for small image size
- **Health Checks**: Built-in health check endpoint with `--health-check` flag
- **Volume Mapping**: Config persistence through volume mounts
- **Non-root Execution**: Runs as dedicated application user (UID 1000)
- **RISCV64 Support**: Special build handling for RISC-V architecture

### Security Features

- **Non-root Execution**: Runs as dedicated application user
- **Minimal Permissions**: Only required network and file access
- **Token Security**: Secure token storage and handling
- **No Credential Logging**: Prevents token exposure in logs

### Scalability

- **Horizontal Scaling**: Multiple container instances
- **Resource Efficiency**: Low CPU and memory usage
- **Independent Operation**: No shared state between instances
- **Container Orchestration**: Compatible with Docker Compose/Kubernetes

## Logging and Monitoring

### Structured Logging

- **Contextual Information**: User, channel, and operation context
- **Color-coded Output**: Easy-to-read console logs
- **Debug Support**: Optional verbose logging mode
- **Performance Metrics**: API response times and success rates

### Observability Features

- **API Monitoring**: Request/response tracking
- **Rate Limit Tracking**: Usage patterns and quotas
- **Connection Statistics**: IRC connection health
- **Error Patterns**: Failure analysis and trends

## Configuration Validation

### Validation Rules

- **Required Fields**: Username, tokens, channels, client credentials
- **Format Validation**: Token length, username format, channel names
- **Placeholder Detection**: Prevents use of example/placeholder values
- **Duplicate Prevention**: Handles duplicate usernames gracefully

### Error Reporting

- **Field-Specific Errors**: Clear validation messages
- **Graceful Handling**: Invalid users skipped with warnings
- **Continued Operation**: Valid users continue despite invalid entries

## Performance Characteristics

### Resource Usage

- **Low Memory**: ~30-40MB per bot instance
- **Minimal CPU**: Event-driven, non-polling architecture
- **Efficient I/O**: Async HTTP and IRC operations
- **Scalable Design**: Linear scaling with user count

### Response Times

- **Immediate Color Changes**: No artificial delays
- **Fast API Calls**: Optimized HTTP client with connection pooling
- **Real-time IRC**: Event-driven message processing
- **Quick Startup**: Fast bot initialization and connection

## Dependencies and Requirements

### Runtime Dependencies

- **aiohttp 3.12+**: Primary async HTTP client for Twitch API communication
- **httpx 0.28+**: Secondary HTTP client for specific operations
- **watchdog 3.0+**: File system monitoring for live configuration reload
- **Python 3.13+**: Core runtime environment

### Development Dependencies

- **black**: Code formatting for consistent style
- **isort**: Import statement organization
- **flake8**: Code linting and style checking
- **mypy**: Static type checking
- **bandit**: Security vulnerability scanning
- **pre-commit**: Git hook automation

### System Requirements

- **Python 3.13+**: Tested and optimized for Python 3.13.7
- **Docker**: Optional for containerized deployment
- **Network Access**: Outbound HTTPS (Twitch API) and IRC connections
- **File System**: Read/write access for configuration persistence

This functional documentation reflects the actual implementation and behavior of the Twitch Color Changer Bot as currently deployed.
