# Twitch ColorChanger Bot Specification

## Application Overview

The Twitch ColorChanger Bot is a multi-user application designed to automatically change a Twitch user's chat color after each message they send in chat. The bot supports both preset Twitch colors and random hex colors (for users with Prime or Turbo subscriptions). It is built for reliability and unattended operation, capable of running for weeks or months without intervention.

The application uses modern Twitch APIs, including EventSub WebSocket for real-time chat connectivity and OAuth 2.0 for secure authentication. It supports multiple users simultaneously, each with their own configuration, and provides runtime controls via chat commands.

## Main Features

### Core Functionality
- **Automatic Color Changes**: Changes the user's chat color immediately after each message they send
- **Multi-User Support**: Runs multiple bot instances for different Twitch accounts concurrently
- **Flexible Color Palette**: Supports Twitch preset colors and random hex colors (Prime/Turbo users only)
- **Real-Time Chat Integration**: Uses EventSub WebSocket for reliable, low-latency message detection
- **Automatic Token Management**: Handles OAuth token setup, validation, and refresh without user intervention

### User Controls
- **Runtime Toggle**: Enable/disable automatic color changes via chat commands (`cce`/`ccd`)
- **Manual Color Setting**: Set specific colors using `ccc <color>` command
- **Persistent State**: Color change settings persist across restarts

### Operational Features
- **Docker Support**: Multi-platform container deployment (amd64, arm64, arm/v7, arm/v6)
- **Configuration Persistence**: Interactive setup with automatic config file management
- **Error Recovery**: Automatic reconnection, retry logic, and fallback mechanisms
- **Smart Prime/Turbo Detection**: Automatically detects subscription status and adjusts color capabilities

## Core Workflows

### 1. Application Startup
1. Load configuration from JSON file
2. Validate and normalize user configurations
3. For each user:
   - Set up OAuth tokens (automatic device flow if needed)
   - Resolve channel names to user IDs
   - Establish EventSub WebSocket connection
   - Subscribe to chat message events
4. Begin listening for messages

### 2. Message Processing
1. Receive chat message via EventSub WebSocket
2. Check if message sender matches bot user
3. If automatic color changes enabled:
   - Select random color (hex or preset based on subscription)
   - Send color change request to Twitch API
   - Handle success/failure and retry logic

### 3. Runtime Commands
1. Detect command messages from bot user
2. Parse command (`cce`, `ccd`, `ccc <color>`)
3. Update configuration state
4. Persist changes to config file

### 4. Error Recovery
1. Detect connection failures or API errors
2. Attempt reconnection with exponential backoff
3. Refresh OAuth tokens if expired
4. Fall back to preset colors if hex colors fail repeatedly

## High-Level Components

### Main Entry Point (`src/main.py`)
- Application initialization and shutdown
- Configuration loading and validation
- Bot manager instantiation
- Error handling and logging setup

### Configuration System (`src/config/`)
- **UserConfig Model**: Pydantic model for user settings with validation
- **Normalization**: Channel name processing, duplicate removal, case handling
- **Persistence**: Async config file updates with debouncing

### Bot Management (`src/bot/`)
- **TwitchColorBot**: Core bot instance managing connection and message handling
- **BotManager**: Coordinates multiple bot instances, lifecycle management
- **Lifecycle Manager**: Handles bot startup, shutdown, and restarts

### Chat Integration (`src/chat/`)
- **EventSub Backend**: WebSocket connection and message processing
- **Subscription Manager**: Manages EventSub subscriptions and renewals
- **Channel Resolver**: Caches and resolves channel names to user IDs
- **Message Processor**: Parses incoming messages and triggers actions

### Color Management (`src/color/`)
- **Color Service**: Handles color change requests with retry and fallback logic
- **Color Utilities**: Random color generation, preset validation
- **Fallback Logic**: Automatic switching from hex to preset colors

### Authentication (`src/auth_token/`)
- **Token Manager**: OAuth token validation and refresh
- **Device Flow**: Automatic token setup via Twitch device authorization
- **Client Management**: Handles client credentials and token persistence

### API Integration (`src/api/`)
- **TwitchAPI Client**: Async wrapper for Twitch Helix API endpoints
- **User Resolution**: Login name to user ID mapping
- **Token Validation**: OAuth token verification

## Twitch Integration Details

### EventSub WebSocket
- **Connection**: `wss://eventsub.wss.twitch.tv/ws`
- **Events**: `channel.chat.message` (filtered to bot user's messages)
- **Reconnection**: Automatic handling of session reconnect messages
- **Subscription Verification**: Periodic checks and renewal of subscriptions

### OAuth Scopes
- `user:read:chat`: Receive chat messages via EventSub
- `user:manage:chat_color`: Change chat color via API

### API Endpoints
- **Color Change**: `PUT /helix/chat/color` with user_id and color parameters
- **User Validation**: `GET /helix/users` for user ID resolution
- **Token Validation**: `GET https://id.twitch.tv/oauth2/validate`

### Authentication Flow
1. Device code generation via `POST /helix/oauth2/device` (internal)
2. User authorization at displayed URL
3. Token exchange and storage
4. Automatic refresh before expiration

## Configuration Structure

The application uses a JSON configuration file (default: `twitch_colorchanger.conf`) with the following structure:

```json
{
  "users": [
    {
      "username": "your_twitch_username",
      "client_id": "twitch_app_client_id",
      "client_secret": "twitch_app_client_secret",
      "channels": ["channel1", "channel2"],
      "is_prime_or_turbo": true,
      "enabled": true,
      "access_token": "oauth_access_token",
      "refresh_token": "oauth_refresh_token",
      "token_expiry": "2024-01-01T00:00:00Z"
    }
  ]
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | string | Yes | Twitch username (3-25 characters) |
| `client_id` | string | Yes* | Twitch app client ID (*required for token setup) |
| `client_secret` | string | Yes* | Twitch app client secret (*required for token setup) |
| `channels` | array | Yes | List of channel names to monitor (no '#' prefix) |
| `is_prime_or_turbo` | boolean | No | Whether user has Prime/Turbo (default: true) |
| `enabled` | boolean | No | Whether automatic color changes are enabled (default: true) |
| `access_token` | string | No | OAuth access token (auto-populated) |
| `refresh_token` | string | No | OAuth refresh token (auto-populated) |
| `token_expiry` | datetime | No | Token expiration timestamp (auto-managed) |

### Configuration Validation
- Usernames: 3-25 characters, alphanumeric + underscore
- Client credentials: Minimum 10 characters each
- Channels: Normalized to lowercase, deduplicated, '#' prefix stripped
- Authentication: Either valid tokens or client credentials required

### Runtime Configuration Updates
- `enabled` field updated via chat commands
- Token fields auto-updated after refresh/setup
- Changes persisted asynchronously with debouncing

## Key Behaviors

### Color Change Logic
- **Trigger**: After each message sent by the bot user
- **Selection**: Random hex (Prime/Turbo) or preset color
- **Exclusion**: Avoids repeating the last used color
- **Fallback**: Switches to presets after repeated hex failures

### Command Processing
- **Sender Check**: Only responds to bot user's own messages
- **Commands**:
  - `cce`: Enable automatic color changes
  - `ccd`: Disable automatic color changes
  - `ccc <color>`: Set specific color (works even when disabled)
- **Color Formats**: Hex (#aabbcc, aabbcc), preset names (case-insensitive)

### Error Handling
- **Network Issues**: Exponential backoff reconnection (1-300s)
- **API Errors**: Retry with backoff, token refresh on 401
- **Rate Limits**: Wait and retry, no special handling beyond standard backoff
- **Invalid Colors**: Log warning, no action taken

### Subscription Detection
- **Hex Rejection Tracking**: Counts 400/403 errors on hex colors
- **Fallback Trigger**: After 2+ rejections, disable hex colors permanently
- **Persistence**: Saves fallback preference to config

### Connection Management
- **WebSocket**: Auto-reconnect on failure or session reconnect
- **Subscriptions**: Re-establish after reconnection
- **Channel Joining**: Supports multiple channels per user

### Operational Resilience
- **Unattended Operation**: Designed for weeks/months of continuous operation
- **Resource Management**: Shared HTTP sessions, connection pooling
- **Graceful Shutdown**: Proper cleanup on SIGTERM/SIGINT
- **Configuration Reload**: Supports config changes without restart

This specification provides a complete functional overview of the Twitch ColorChanger Bot, enabling recreation from scratch while focusing on behavior and integration rather than implementation details.
