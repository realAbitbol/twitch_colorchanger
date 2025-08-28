# Multi-User Twitch ColorChanger

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Automatically change your Twitch username color after each message you send in chat. Supports both preset Twitch colors and random hex colors (for Prime/Turbo users). **Supports multiple users and Docker deployment!**

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Technical Documentation](#technical-documentation)
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
- **🐳 Docker Ready**: Multi-platform support (amd64, arm64, arm/v7, arm/v6, riscv64)
- **💾 Persistent Config**: Interactive setup with configuration file persistence
- **👀 Live Config Reload**: Automatically detects config file changes and restarts bots without manual intervention

### Additional Features

- **🏗️ Colored Logging**: Clean, colored console output for easy monitoring
- **🛡️ Error Handling**: Automatic retries with exponential backoff
- **🎯 Smart Turbo/Prime Detection**: Automatically detects non-Turbo/Prime users and falls back to preset colors
- **💾 Persistent Fallback**: Saves Turbo/Prime limitations to config for permanent fallback behavior
- **⚡ HTTP Client**: Simple and reliable HTTP client for API communication
- **✅ Configuration Validation**: Comprehensive validation with detailed error reporting
- **📊 Rate Limiting**: Smart rate limiting with quota tracking and logging

---

## Requirements

- **Python 3.13+** (tested with Python 3.13.7)
- **Docker** (optional, for containerized deployment)
- **Twitch Account** with Prime/Turbo subscription (for hex colors) or regular account (for preset colors)

### Dependencies

The bot requires minimal dependencies for optimal performance:

- **Core**: `aiohttp>=3.9.0,<4.0.0` - Async HTTP client for Twitch API communication
- **Live Config**: `watchdog>=3.0.0,<4.0.0` - File system monitoring for runtime config reload

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

#### Option A: Direct Run

Create a config file from the sample:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
# Edit the config file with your credentials
python main.py
```

#### Option B: Docker

Create a config file from the sample:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
# Edit the config file with your credentials
```

Then run:

```bash
docker run -it --rm \
  -v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf \
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
    volumes:
      - ./twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf
    restart: unless-stopped
```

---

## Configuration

### Configuration File

The bot uses a configuration file for all settings: `twitch_colorchanger.conf`

Copy the sample file to get started:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
```

Edit the configuration file with your credentials:

The bot loads settings from `twitch_colorchanger.conf` by default. You can use a custom config file by setting the `TWITCH_CONF_FILE` environment variable:

```bash
# Use a custom config file
export TWITCH_CONF_FILE=/path/to/my-config.conf
python main.py

# Or for Docker
docker run -e TWITCH_CONF_FILE=/app/config/my-config.conf \
  -v $(pwd)/my-config.conf:/app/config/my-config.conf \
  damastah/twitch-colorchanger:latest
```

Configuration file format:

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
- **Simple configuration**: Single configuration file for all settings
- **Custom config file**: Use `TWITCH_CONF_FILE` environment variable to specify custom config file path
- **Docker support**: Containerized deployment with mounted config file

### Advanced Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug logging | `false` |
| `TWITCH_CONF_FILE` | Path to configuration file | `twitch_colorchanger.conf` |

### Runtime Configuration Changes

The bot automatically watches for changes to the configuration file and restarts with the new settings **without requiring manual intervention**. This feature enables:

- **Adding new users**: Simply add a new user to the `users` array in the config file
- **Removing users**: Delete or comment out users from the config file  
- **Updating settings**: Modify any user settings (channels, colors, etc.) and they'll take effect immediately
- **Zero downtime**: Bots restart automatically when valid config changes are detected

**Requirements:**

- Install the `watchdog` package: `pip install watchdog` (included in `requirements.txt`)
- Config file must contain valid JSON with at least one valid user

**Example workflow:**

1. Start the bot: `python main.py`
2. Edit `twitch_colorchanger.conf` in your editor
3. Save the file - bots automatically restart with new config
4. Check the console output for restart confirmation

**Note:** Invalid configuration changes are ignored with warnings logged to console. Bot-initiated updates (like token refreshes) do not trigger restarts to prevent infinite loops.

### Docker Configuration

The container runs as root for compatibility with mounted volumes. Mount your config file directly:

```bash
docker run -v $PWD/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf damastah/twitch-colorchanger:latest
```

If you encounter permission issues, ensure the mounted config file is readable by the container.

### Debug Mode

Enable detailed logging for troubleshooting:

```bash
# Local debugging
DEBUG=true python main.py

# Docker with debug logging
docker run -e DEBUG=true damastah/twitch-colorchanger:latest
```

**Debug Output Includes:**

- Config file watching events
- Token refresh operations
- Rate limiting details
- IRC message parsing
- Bot restart confirmations

### Monitoring Live Configuration

Watch for these console messages to monitor config changes:

```text
👀 Config file watcher enabled for: twitch_colorchanger.conf
📁 Config file changed: /path/to/twitch_colorchanger.conf
✅ Config validation passed - 2 valid user(s)
🔄 Config change detected, restarting bots...
📊 Config updated: 1 → 2 users
```

**Troubleshooting Config Watching:**

- **No watcher messages**: Install `watchdog` package: `pip install watchdog`
- **Changes ignored**: Check JSON syntax and ensure at least one valid user
- **Infinite restarts**: Bot token updates are filtered out automatically
- **File permissions**: Ensure config file is readable by the application

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

- Config not loading: confirm config file is mounted correctly `-v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf`
- Configuration issues: check that your config file has valid JSON format and contains user configurations
- Color not changing: non‑Prime/Turbo accounts can only use preset colors

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
- All logs are colored for easy reading.

If issues persist, open an issue with: platform, Python/Docker version, relevant log snippet (exclude tokens).

---

## Technical Documentation

For developers and technical implementation details:

- **[FUNCTIONAL_DOCUMENTATION.md](FUNCTIONAL_DOCUMENTATION.md)** - Detailed feature specifications and behavior
- **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** - Complete technical guide to rebuild this application from scratch

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

# Format code
black .
isort .
```

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

### Why GPL v3?

We chose GPL v3 to ensure this software remains free and open source. Any derivative works must also be open source under compatible licenses, fostering a community of shared improvements.
