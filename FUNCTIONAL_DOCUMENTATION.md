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
7. **Token Management**: Automatic token refresh with proactive expiry checking
8. **IRC Connection**: Custom IRC client with reliable channel joining and message processing
9. **Docker Support**: Multi-architecture container images with simplified deployment
10. **Live Configuration Reload**: Automatic bot restart when config file changes externally

### Color Change Flow

```text
User sends message → IRC client receives → Bot detects own message → 
Generate new color (avoiding current) → API call to Twitch → Color changed
```

## Token Lifecycle Management

### Startup Behavior

- **Force Refresh**: Immediately refreshes tokens on startup if refresh token exists
- **Token Validation**: Validates access token against Twitch API
- **Expiry Tracking**: Records token expiry time for proactive refresh

### Periodic Maintenance

- **10-Minute Checks**: Validates tokens every 600 seconds
- **Proactive Refresh**: Refreshes when <1 hour remaining
- **Fallback Validation**: API validation if expiry time unknown
- **Config Persistence**: Updates config file with new tokens

### Error Handling

- **Automatic Retry**: Exponential backoff for temporary failures
- **Token Invalidation**: Handles revoked or expired tokens gracefully
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
      "use_random_colors": true
    }
  ]
}
```

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

## Multi-Bot Orchestration

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

- **Server**: irc.chat.twitch.tv:6667
- **Authentication**: OAuth token-based authentication
- **Capabilities**: Membership, tags, and commands capabilities
- **Keepalive**: PING/PONG handling for connection stability

### Message Processing

- **Real-time Processing**: Event-driven message handling
- **Own Message Detection**: Only processes messages from the bot's own username
- **Channel Management**: Supports multiple channels per bot
- **Debug Support**: Optional verbose message logging

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
- **Health Checks**: Built-in health check endpoint
- **Volume Mapping**: Config persistence through volume mounts

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

This functional documentation reflects the actual implementation and behavior of the Twitch Color Changer Bot as currently deployed.
