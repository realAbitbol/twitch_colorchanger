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
- **🔑 Token Management**: Automatic token refresh for seamless operation
- **🐳 Docker Ready**: Unattended mode with environment variables
- **💾 Persistent Config**: Interactive setup with configuration file persistence

### Enhanced Features

- **🏗️ Structured Logging**: JSON output for production, colored logs for development
- **🛡️ Advanced Error Handling**: Automatic retries with exponential backoff
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
| `TWITCH_USE_RANDOM_COLORS_1` | Use random hex colors | `true`/`false` |

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

**Features:**

- **Automatic token refresh**: Tokens are refreshed and saved automatically
- **Multi-user support**: Add multiple users to the same config file
- **Interactive management**: Choose to use existing config, add users, or create new
- **Environment override**: Use `TWITCH_CONF_FILE` to specify custom config file path

---

## Troubleshooting

### Common Issues

#### Authentication Problems

- **Missing scopes**: Ensure your token has `chat:read` and `user:manage:chat_color`
- **Invalid tokens**: Regenerate tokens using [twitchtokengenerator.com](https://twitchtokengenerator.com)
- **Client credentials**: Verify your Client ID and Client Secret are correct

#### Color Change Issues

- **Color not changing**: Prime/Turbo users can use hex colors; others use preset Twitch colors
- **Rate limits**: Twitch API allows color changes every ~1.5 seconds
- **Channel permissions**: Ensure the bot has permission to change colors in the channel

#### Docker Issues

- **Environment variables**: Ensure all required environment variables are set
- **Volume mounting**: Mount a volume for config persistence: `-v $PWD/config:/app/config`
- **Permissions**: Check that the container has write access to mounted volumes

### Multi-User Specific Issues

- **Only some users working**: Check that all numbered environment variables are set correctly
- **Users not detected**: Environment variable names must be exact - use `_1`, `_2`, `_3` etc.
- **Config file conflicts**: Multi-user configs use `{"users": [...]}` format
- **Mixed environment and config**: Environment variables take precedence over config file

### Performance Issues

- **Memory leaks**: The bot includes automatic memory leak detection
- **Connection issues**: HTTP connection pooling optimizes API performance
- **High CPU usage**: Disable debug logging in production (`DEBUG=false`)
- **API failures**: Automatic retry logic handles transient failures

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
