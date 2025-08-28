# Multi-User Twitch ColorChanger

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Automatically change your Twitch username color after each message you send in chat. Supports both preset Twitch colors and random hex colors (for Prime/Turbo users). **Now supports multiple users and Docker unattended mode!**

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Core Features

- **🎨 Dynamic Color Changes**: Automatically changes your Twitch chat color after every message
- **👥 Multi-User Support**: Run multiple bots for different Twitch accounts simultaneously
- **🎲 Flexible Colors**: Supports both preset Twitch colors and random hex colors (Prime/Turbo users)
- **🔄 Universal Compatibility**: Works with Chatterino, web chat, or any IRC client
- **🔑 Token Management**: Forced startup refresh + periodic (10 min) checks; refreshes automatically when <1h remains
- **🐳 Docker Ready**: Multi-platform support (amd64, arm64, arm/v7, arm/v6, riscv64) with unattended mode
- **💾 Persistent Config**: Interactive setup with configuration file persistence

### Enhanced Features

- **🏗️ Structured Logging**: JSON output for production, colored logs for development
- **🛡️ Advanced Error Handling**: Automatic retries with exponential backoff
- **🎯 Smart Turbo/Prime Detection**: Automatically detects non-Turbo/Prime users and falls back to preset colors
- **💾 Persistent Fallback**: Saves Turbo/Prime limitations to config for permanent fallback behavior
- **⚡ HTTP Optimization**: Connection pooling and resource management
- **🔍 Memory Protection**: Automatic monitoring and cleanup
- **✅ Configuration Validation**: Comprehensive validation with detailed error reporting
- **📊 Observability**: API performance monitoring and statistics

---

## Requirements

- **Python 3.13+** (tested with Python 3.13.7)
- **Docker** (optional, for containerized deployment)
- **Twitch Account** with Prime/Turbo subscription (for hex colors) or regular account (for preset colors)

### Dependencies

The bot uses only one core dependency for optimal performance:

- `aiohttp>=3.9.0,<4.0.0` - Async HTTP client for Twitch API communication

All dependencies are automatically installed via `requirements.txt`.

---

## Quick Start

### 1. Get Twitch Credentials

#### Create a Twitch App

1. Go to [Twitch Dev Console](https://dev.twitch.tv/console/apps) and sign in
2. Click **Register Your Application**
3. Name your app (e.g., `TwitchColorBot`)
4. Set **OAuth Redirect URLs** to: `https://twitchtokengenerator.com`
5. Set **Category** to `Chat Bot` or `Other`
6. Click **Create** and copy your **Client ID**
7. Click **Manage** → **New Secret** to generate a **Client Secret**

#### Generate Tokens

Use [twitchtokengenerator.com](https://twitchtokengenerator.com):

- Enter your Client ID and Client Secret
- Select scopes: `chat:read`, `user:manage:chat_color` (optional: `chat:edit`)
- Click **Generate Token** and save the **Access Token** and **Refresh Token**

### 2. Run the Bot

#### Option A: Interactive Setup (Recommended)

```bash
python main.py
```

Follow the prompts to configure your bot(s).

#### Option B: Docker (Single User)

```bash
docker run -it --rm \
  -e TWITCH_USERNAME=your_username \
  -e TWITCH_ACCESS_TOKEN=your_access_token \
  -e TWITCH_REFRESH_TOKEN=your_refresh_token \
  -e TWITCH_CLIENT_ID=your_client_id \
  -e TWITCH_CLIENT_SECRET=your_client_secret \
  -e TWITCH_CHANNELS=channel1,channel2 \
  damastah/twitch-colorchanger:latest
```

#### Option C: Docker (Multi-User)

```bash
docker run -it --rm \
  -e TWITCH_USERNAME_1=user1 \
  -e TWITCH_ACCESS_TOKEN_1=token1 \
  -e TWITCH_REFRESH_TOKEN_1=refresh1 \
  -e TWITCH_CLIENT_ID_1=client1 \
  -e TWITCH_CLIENT_SECRET_1=secret1 \
  -e TWITCH_CHANNELS_1=channel1,channel2 \
  -e TWITCH_USERNAME_2=user2 \
  -e TWITCH_ACCESS_TOKEN_2=token2 \
  -e TWITCH_REFRESH_TOKEN_2=refresh2 \
  -e TWITCH_CLIENT_ID_2=client2 \
  -e TWITCH_CLIENT_SECRET_2=secret2 \
  -e TWITCH_CHANNELS_2=channel3,channel4 \
  damastah/twitch-colorchanger:latest
```

---

## Usage

### Local Development

```bash
# Clone the repository
git clone https://github.com/realAbitbol/twitch_colorchanger.git
cd twitch_colorchanger

# Install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run the bot
python main.py
```

### Docker Deployment

#### Build Locally

```bash
docker build -t twitch-colorchanger .
docker run -it --rm twitch-colorchanger
```

#### Pre-built Images

Multi-platform images are available on:

- **Docker Hub**: `damastah/twitch-colorchanger:latest`
- **GitHub Container Registry**: `ghcr.io/realabitbol/twitch-colorchanger:latest`

**Supported Architectures:**

- `linux/amd64` - Standard x86_64 (Intel/AMD)
- `linux/arm64` - ARM 64-bit (Apple Silicon, modern ARM servers)
- `linux/arm/v7` - ARM 32-bit (Raspberry Pi 2/3/4)
- `linux/arm/v6` - ARM v6 (Raspberry Pi Zero/1)
- `linux/riscv64` - RISC-V 64-bit

#### Docker Compose

Copy `docker-compose.yml-sample` to `docker-compose.yml` and customize:

```yaml
services:
  twitch-colorchanger:
    image: damastah/twitch-colorchanger:latest
    environment:
      # User 1
      - TWITCH_USERNAME_1=user1
      - TWITCH_ACCESS_TOKEN_1=your_access_token_1
      - TWITCH_REFRESH_TOKEN_1=your_refresh_token_1
      - TWITCH_CLIENT_ID_1=your_client_id_1
      - TWITCH_CLIENT_SECRET_1=your_client_secret_1
      - TWITCH_CHANNELS_1=channel1,channel2
      - TWITCH_USE_RANDOM_COLORS_1=true

      # User 2
      - TWITCH_USERNAME_2=user2
      - TWITCH_ACCESS_TOKEN_2=your_access_token_2
      - TWITCH_REFRESH_TOKEN_2=your_refresh_token_2
      - TWITCH_CLIENT_ID_2=your_client_id_2
      - TWITCH_CLIENT_SECRET_2=your_client_secret_2
      - TWITCH_CHANNELS_2=channel3,channel4
      - TWITCH_USE_RANDOM_COLORS_2=false
    volumes:
      - ./config:/app/config
    restart: unless-stopped
```

---

## Configuration

### Environment Variables

#### Multi-User Configuration

Use numbered environment variables for multiple users:

| Variable | Description | Example |
|----------|-------------|---------|
| `TWITCH_USERNAME_1` | Twitch username for user 1 | `user1` |
| `TWITCH_ACCESS_TOKEN_1` | OAuth access token | `abc123...` |
| `TWITCH_REFRESH_TOKEN_1` | OAuth refresh token | `def456...` |
| `TWITCH_CLIENT_ID_1` | Twitch app client ID | `client_id_1` |
| `TWITCH_CLIENT_SECRET_1` | Twitch app client secret | `client_secret_1` |
| `TWITCH_CHANNELS_1` | Channels to join (comma-separated) | `channel1,channel2` |
| `TWITCH_USE_RANDOM_COLORS_1` | Use random hex colors (legacy: `USE_RANDOM_COLORS_1`) | `true`/`false` |

Repeat with `_2`, `_3`, etc. for additional users.

#### Single User Configuration (Legacy)

| Variable | Description | Example |
|----------|-------------|---------|
| `TWITCH_USERNAME` | Twitch username | `your_username` |
| `TWITCH_ACCESS_TOKEN` | OAuth access token | `abc123...` |
| `TWITCH_REFRESH_TOKEN` | OAuth refresh token | `def456...` |
| `TWITCH_CLIENT_ID` | Twitch app client ID | `client_id` |
| `TWITCH_CLIENT_SECRET` | Twitch app client secret | `client_secret` |
| `TWITCH_CHANNELS` | Channels to join | `channel1,channel2` |
| `TWITCH_USE_RANDOM_COLORS` | Use random hex colors | `true`/`false` |

#### Advanced Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug logging | `false` |
| `LOG_FORMAT` | Log format (`json` or `colored`) | `colored` |
| `LOG_FILE` | Path to log file | None |
| `FORCE_COLOR` | Force colored logs | `true` |
| `PYTHONUNBUFFERED` | Disable output buffering | `1` |

### Configuration File

The bot automatically saves settings to `twitch_colorchanger.conf`:

```json
{
  "users": [
    {
      "username": "your_username",
      "access_token": "your_access_token",
      "refresh_token": "your_refresh_token",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["channel1", "channel2"],
      "use_random_colors": true
    }
  ]
}
```

Features:

- **Automatic token lifecycle**: Forced refresh at startup then every 10 minutes if expiring (<1h) or validation fails
- **Multi-user support**: Add multiple users to the same config file
- **Interactive management**: Choose to use existing config, add users, or create new
- **Environment override**: Use `TWITCH_CONF_FILE` to specify custom config file path
- **Targeted precedence**: Environment overrides channels & random color flags; config file retains tokens & client credentials

### Docker Permission Notes

The container now always runs as root for simplicity and maximum compatibility with NAS / mounted volumes. Mount only the config directory for persistence:

```bash
docker run -v $PWD/config:/app/config damastah/twitch-colorchanger:latest
```

If you still encounter write issues on a NAS, ensure the mounted path is writable by root inside the container (most setups allow this by default). No user remapping variables are required or supported anymore. To fix rare NAS permission issues manually (SSH), ensure the directory is writable by root.

### Debug Mode

Enable detailed logging for troubleshooting:

```bash
# Local debugging
DEBUG=true python main.py

# Docker with debug logging
docker run -e DEBUG=true -e LOG_FORMAT=json damastah/twitch-colorchanger:latest

# File logging
docker run -e LOG_FILE=/app/logs/bot.log -v $PWD/logs:/app/logs damastah/twitch-colorchanger:latest
```

---

### Channel Join Reliability

Each channel JOIN waits for confirmation (numeric 366). If not received within 30 seconds a single retry is issued (max 2 attempts). Final failure is logged after the second timeout.

### Token Strategy

On startup the bot forces a token refresh (if a refresh token exists) for a full validity window. A background task then runs every 10 minutes:

- If expiry is known and < 1 hour → refresh
- If no expiry is tracked → validate via a lightweight users endpoint call, refresh on failure

## Troubleshooting

### Authentication

- Missing scopes: ensure tokens include `chat:read` and `user:manage:chat_color` (and optionally `chat:edit`).
- Invalid / expired tokens: regenerate tokens at [twitchtokengenerator.com](https://twitchtokengenerator.com).
- Client credentials mismatch: verify Client ID and Secret match the generated tokens.

### Docker

- Config not persisting: confirm volume mount `-v $PWD/config:/app/config` exists and directory is writable.
- No users loaded: ensure environment variables use numbered suffixes (`_1`, `_2`, ...).
- Color not changing: non‑Prime/Turbo accounts can only use preset colors.

### Turbo/Prime Limitations

- **Automatic Detection**: The bot automatically detects when a user lacks Turbo/Prime subscription for hex colors
- **Smart Fallback**: Automatically switches to preset Twitch colors when hex colors fail
- **Persistent Settings**: Saves the fallback preference to config file to avoid repeated API errors
- **Seamless Operation**: Users continue receiving color changes without interruption

### Rate / API Issues

- Too many requests: Twitch may temporarily limit rapid color changes; the bot already spaces them—avoid manual spamming.
- Network errors: transient failures are retried automatically; persistent 401 means token refresh failed (recreate tokens).

### Logging & Debugging

- Set `DEBUG=true` for verbose logs.
- Use `LOG_FORMAT=json` for structured output in aggregators.

If issues persist, open an issue with: platform, Python/Docker version, relevant log snippet (exclude tokens).

---

## Architecture

### Project Structure

```text
twitch_colorchanger/
├── main.py                     # Application entry point
├── src/                        # Core application modules
│   ├── __init__.py            # Package initialization
│   ├── bot.py                 # TwitchColorBot class (core logic)
│   ├── bot_manager.py         # Multi-bot management
│   ├── config.py              # Configuration management
│   ├── config_validator.py    # Configuration validation
│   ├── simple_irc.py          # Custom IRC client
│   ├── colors.py              # Color definitions and utilities
│   ├── utils.py               # Utility functions
│   ├── logger.py              # Structured logging system
│   ├── error_handling.py      # Advanced error handling
│   ├── http_client.py         # HTTP connection pooling
│   ├── rate_limiter.py        # Rate limiting for API requests
│   └── memory_monitor.py      # Memory leak detection
├── requirements.txt            # Python dependencies
├── Dockerfile                 # Container definition
├── docker-compose.yml-sample  # Docker Compose template
├── FUNCTIONAL_DOCUMENTATION.md # Feature specifications
└── IMPLEMENTATION_GUIDE.md    # Technical implementation details
```

### Key Components

#### Core System

- **`main.py`**: Enhanced entry point with error handling and graceful shutdown
- **`src/config.py`**: Handles environment variables and interactive setup
- **`src/bot.py`**: Individual bot instance with color changing logic
- **`src/bot_manager.py`**: Manages multiple bots and handles shutdown
- **`src/simple_irc.py`**: Custom Twitch IRC client implementation

#### Advanced Features

- **`src/logger.py`**: Structured logging with JSON/colored output
- **`src/config_validator.py`**: Comprehensive configuration validation
- **`src/error_handling.py`**: Custom exception hierarchy with retry logic
- **`src/http_client.py`**: HTTP connection pooling with memory leak prevention
- **`src/rate_limiter.py`**: Intelligent rate limiting for Twitch API
- **`src/memory_monitor.py`**: Memory leak detection and prevention

### Design Principles

- **Modular Architecture**: Clear separation of concerns for maintainability
- **Reliability**: Advanced error handling and automatic recovery
- **Performance**: Optimized resource management and connection pooling
- **Observability**: Comprehensive logging and monitoring
- **Extensibility**: Easy to add features without affecting other components
- **Security**: Secure token handling and configuration validation

---

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/realAbitbol/twitch_colorchanger.git
cd twitch_colorchanger

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest

# Run linting
python -m black src/
python -m isort src/
```

### Security Considerations

- **Token Security**: Never commit tokens to version control
- **Environment Variables**: Use secure methods to pass sensitive data
- **Network Security**: The bot communicates securely with Twitch APIs over HTTPS
- **Access Control**: Limit bot permissions to required scopes only

---

## License

This project is licensed under the GNU GPL v3. See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- Twitch API for providing the color change functionality
- The open-source community for inspiration and tools
- Contributors who help improve this project

---

**⭐ Star this repository** if you find it useful!
