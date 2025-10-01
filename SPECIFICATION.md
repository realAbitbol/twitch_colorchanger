# Twitch ColorChanger Functional Specification

## Overview

Twitch ColorChanger is a bot application that automatically changes a Twitch user's chat color after each message they send in chat. The application supports multiple users running simultaneously, with automatic token management and persistent configuration.

## Core Functionality

### Automatic Color Changes

- **Trigger**: The bot monitors chat messages sent by its own account in configured channels
- **Action**: After each message sent by the bot user, the chat color is automatically changed to a new random color
- **Color Types**:
  - Preset Twitch colors (available to all users)
  - Random hex colors (available only to Prime/Turbo subscribers)
- **Fallback**: If hex colors are not available (non-Prime/Turbo), the bot automatically falls back to preset colors

### Multi-User Support

- **Multiple Bots**: The application can run multiple bot instances simultaneously, each managing a different Twitch account
- **Independent Operation**: Each bot operates independently with its own configuration, channels, and color settings
- **Shared Resources**: Bots share HTTP sessions and application context for efficiency

### Chat Commands

The bot responds to commands sent by its own account in any connected channel. Commands are processed in real-time and can control the bot's behavior during operation.

#### Command Reference

- **`cce`** (Color Change Enable)
  - **Purpose**: Enables automatic color changes after each message
  - **Usage**: Send `cce` as a message in any connected channel
  - **Effect**: Sets the bot's `enabled` flag to `true`
  - **Persistence**: The setting is automatically saved to the configuration file and survives bot restarts
  - **Behavior**: Once enabled, the bot will change colors after every message it sends
  - **Example**: `cce` → Bot responds with automatic color changes enabled

- **`ccd`** (Color Change Disable)
  - **Purpose**: Disables automatic color changes
  - **Usage**: Send `ccd` as a message in any connected channel
  - **Effect**: Sets the bot's `enabled` flag to `false`
  - **Persistence**: The setting is automatically saved to the configuration file and survives bot restarts
  - **Behavior**: Bot stops changing colors automatically but remains connected and can still respond to manual commands
  - **Example**: `ccd` → Bot responds with automatic color changes disabled

- **`ccc <color>`** (Color Change Command)
  - **Purpose**: Immediately sets the chat color to a specific value
  - **Usage**: Send `ccc <color>` where `<color>` is the desired color specification
  - **Effect**: Forces an immediate color change regardless of the `enabled` state
  - **Persistence**: This is a one-time change and does not affect the `enabled` flag
  - **Color Formats**:
    - **Preset names**: Case-insensitive Twitch color names (e.g., `red`, `Blue`, `sea_green`)
    - **Hex colors**: 6-digit hex codes with or without `#` prefix (e.g., `#ff0000`, `00ff00`)
    - **Short hex**: 3-digit hex codes that expand automatically (e.g., `f00` becomes `#ff0000`)
  - **Validation**: Invalid color specifications are logged but ignored
  - **Prime/Turbo restriction**: Hex colors are ignored for non-Prime/Turbo accounts with an info log message
  - **Examples**:
    - `ccc red` → Sets color to Twitch preset "red"
    - `ccc #ff0000` → Sets color to hex red (Prime/Turbo only)
    - `ccc ABC` → Sets color to `#aabbcc` (Prime/Turbo only)
    - `ccc invalid` → Logs info message, no color change

#### Command Behavior Details

- **Sender Verification**: Commands only work when sent by the bot's own account (other users are ignored)
- **Channel Scope**: Commands work in any channel the bot is connected to
- **No Feedback**: Successful commands execute silently (except for logging)
- **Error Handling**: Invalid commands are logged as info messages but don't interrupt normal operation
- **State Independence**: `ccc` commands bypass the enable/disable toggle
- **Configuration Sync**: Enable/disable changes are immediately persisted to the config file
- **Restart Persistence**: Enable/disable state is restored from config on bot restart

### Configuration Management

- **File-Based**: All settings are stored in a JSON configuration file (`twitch_colorchanger.conf`)
- **Auto-Population**: Tokens are automatically obtained and saved to the configuration file
- **Persistence**: Configuration changes (like enable/disable state) are automatically saved
- **Validation**: Comprehensive validation of configuration with detailed error reporting

## Configuration File Structure

The configuration file is a JSON document with the following structure:

```json
{
  "users": [
    {
      "username": "your_username",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["channel1", "channel2"],
      "is_prime_or_turbo": true,
      "enabled": true,
      "access_token": "auto_populated_access_token",
      "refresh_token": "auto_populated_refresh_token"
    }
  ]
}
```

### Configuration Fields

#### Required Fields

- **username** (string): The Twitch username for the bot account
- **client_id** (string): Twitch application client ID obtained from Twitch Dev Console
- **client_secret** (string): Twitch application client secret (keep secure)
- **channels** (array of strings): List of channel names where the bot should monitor messages
  - Channel names should not include the `#` prefix
  - Case-insensitive but stored in normalized form
  - Duplicates are automatically removed
- **is_prime_or_turbo** (boolean): Whether the account has Prime/Turbo subscription
  - `true`: Enables random hex color support
  - `false`: Limits to preset Twitch colors only

#### Optional Fields

- **enabled** (boolean): Controls automatic color changes
  - `true` (default): Automatic color changes are active
  - `false`: Color changes are disabled, but bot remains connected
  - Can be toggled via `cce`/`ccd` commands and persists across restarts
- **access_token** (string): OAuth access token for API calls
  - Automatically populated during initial setup
  - Refreshed automatically when needed
- **refresh_token** (string): OAuth refresh token for token renewal
  - Automatically populated during initial setup
  - Used to obtain new access tokens

### Configuration Processing

- **Channel Normalization**: Channels are normalized to lowercase and deduplicated
- **Token Management**: Missing tokens trigger automatic device flow authorization
- **Validation**: Configuration is validated on startup with clear error messages
- **Persistence**: Changes to runtime state (like `enabled` flag) are automatically saved

## Authentication and Authorization

### Automatic Token Setup

- **Device Flow**: Uses Twitch's device authorization flow for seamless setup
- **No Manual Intervention**: After providing client credentials, the bot guides the user through authorization
- **Persistent Storage**: Obtained tokens are automatically saved to the configuration file
- **Token Refresh**: Access tokens are automatically refreshed and persisted one hour before they expire to be safe

### Required Scopes

The bot requires the following OAuth scopes:
- `user:read:chat`: Receive chat messages via EventSub
- `user:manage:chat_color`: Change chat color via API

## Chat Integration

### EventSub WebSocket

- **Modern Backend**: Uses Twitch's EventSub WebSocket for reliable chat connectivity
- **Filtered Messages**: Subscribes only to messages from the bot's own account
- **Real-time**: Immediate response to messages without polling

### Channel Monitoring

- **Message Detection**: Only messages sent by the bot's own account trigger color changes
- **Multi-Channel**: Can monitor multiple channels simultaneously
- **Channel-Specific**: Color changes apply globally but require message detection in configured channels

## Color Management

### Color Selection

- **Random Selection**: Each color change selects a random color from available options
- **Exclusion Logic**: Avoids repeating the same color consecutively
- **Type Determination**: Based on `is_prime_or_turbo` setting:
  - Prime/Turbo: Random between hex colors and presets
  - Non-Prime/Turbo: Random preset colors only

### Preset Colors

The bot supports all standard Twitch chat preset colors:
- Blue, BlueViolet, CadetBlue, Chocolate, Coral, DodgerBlue, Firebrick, GoldenRod, Green, HotPink, OrangeRed, Red, SeaGreen, SpringGreen, YellowGreen, etc.

### Hex Colors

- **Format**: 6-digit hexadecimal colors (#RRGGBB)
- **Availability**: Only for Prime/Turbo subscribers
- **Fallback**: Automatically switches to presets if hex colors are rejected

### Random Hex Color Algorithm

The bot uses a sophisticated HSL (Hue, Saturation, Lightness) color space algorithm to generate visually pleasing random hex colors. This approach ensures better color distribution and visual quality compared to simple RGB randomization.

#### Algorithm Overview

1. **HSL Generation**: Random values are generated for hue (0-359°), saturation (60-100%), and lightness (35-75%)
2. **HSL to RGB Conversion**: The HSL values are converted to RGB using standard color space conversion formulas
3. **Hex Formatting**: RGB values are formatted as 6-digit hexadecimal strings
4. **Uniqueness Check**: Generated colors are checked against exclusion lists to avoid repetition
5. **Fallback Strategy**: If a unique color cannot be generated within maximum attempts, returns the last generated color

#### HSL Color Space Benefits

- **Hue Control**: Full 360° spectrum ensures diverse color variety
- **Saturation Management**: 60-100% range avoids washed-out colors while preventing oversaturation
- **Lightness Optimization**: 35-75% range ensures good readability and contrast in chat environments
- **Visual Quality**: HSL-based generation produces more aesthetically pleasing color combinations

#### Configurable Parameters

The algorithm uses several configurable constants that can be overridden via environment variables:

- **COLOR_RANDOM_HEX_MAX_ATTEMPTS** (default: 10): Maximum attempts to generate a unique color
- **COLOR_MAX_HUE** (default: 359): Maximum hue value in degrees (0-359)
- **COLOR_MIN_SATURATION** (default: 60): Minimum saturation percentage
- **COLOR_MAX_SATURATION** (default: 100): Maximum saturation percentage
- **COLOR_MIN_LIGHTNESS** (default: 35): Minimum lightness percentage
- **COLOR_MAX_LIGHTNESS** (default: 75): Maximum lightness percentage
- **COLOR_HUE_SECTOR_SIZE** (default: 60): Hue sector size for HSL to RGB conversion calculations

#### Exclusion Mechanism

- **Purpose**: Prevents immediate color repetition for better visual variety
- **Implementation**: Maintains exclusion lists that can be passed to generation functions
- **Fallback**: If all colors in the palette are excluded, falls back to the full color set
- **Case Insensitive**: Color comparisons are case-insensitive for user-friendly operation

#### Security and Randomness

- **Cryptographic Security**: Uses `secrets.SystemRandom()` for cryptographically secure random number generation
- **Deterministic Exclusion**: Ensures excluded colors are never returned unless all options are exhausted
- **Performance Optimized**: Maximum attempt limits prevent infinite loops while maintaining quality

#### Color Quality Assurance

The algorithm ensures:
- **Readability**: Lightness constraints ensure colors are visible in chat
- **Variety**: Full hue spectrum prevents monotonous color sequences
- **Consistency**: Deterministic exclusion provides predictable behavior
- **Reliability**: Maximum attempt limits guarantee termination

### Color Change Logic

- **API Integration**: Uses Twitch Helix API to change chat colors
- **Error Handling**: Retries on failures with exponential backoff
- **Rate Limiting**: Handles API rate limits gracefully
- **Fallback Strategy**: Falls back to preset colors if hex changes fail repeatedly

## Runtime Behavior

### Startup Process

1. Load and validate configuration file
2. Normalize channel names and remove duplicates
3. Set up token management for each user
4. Establish EventSub WebSocket connections
5. Begin monitoring configured channels
6. Start periodic maintenance tasks

### Message Processing

1. Receive message via EventSub
2. Check if sender matches bot username
3. Process any commands (`cce`, `ccd`, `ccc`)
4. If auto-enabled and no command processed, trigger color change
5. Log message and actions

### Error Recovery

- **Connection Issues**: Automatic reconnection with exponential backoff
- **Token Expiration**: Automatic refresh using stored refresh tokens
- **API Failures**: Retry logic with fallback strategies
- **Configuration Errors**: Clear error messages and graceful degradation

### Shutdown Process

- Disconnect from all chat connections
- Flush pending configuration changes
- Clean up resources and background tasks
- Log shutdown completion

## Deployment Options

### Local Development

- **Direct Run**: Execute with `python -m src.main`
- **Virtual Environment**: Isolated Python environment recommended
- **Configuration**: Local configuration file with full paths

### Docker Deployment

- **Containerized**: Multi-platform Docker images available
- **Volume Mounting**: Configuration and cache files mounted from host
- **Environment Variables**: Override internal constants via environment

### Production Deployment

- **Unattended Operation**: Designed to run for weeks/months without intervention
- **Logging**: Comprehensive logging with configurable levels
- **Monitoring**: Built-in resource monitoring and error reporting

## Security Considerations

- **Token Security**: Access and refresh tokens stored securely
- **Client Secret**: Keep client secrets confidential
- **File Permissions**: Configuration files should have restricted access
- **Network Security**: HTTPS for all API communications
- **Container Security**: Non-root user in Docker deployments

## Limitations and Constraints

- **Prime/Turbo Requirement**: Hex colors require active Prime/Turbo subscription
- **Channel Access**: Bot must be able to read chat in configured channels
- **Rate Limits**: Subject to Twitch API rate limiting
- **Message Ownership**: Only responds to bot's own messages
- **Single Account**: One bot instance per Twitch account