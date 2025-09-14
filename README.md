# Twitch ColorChanger

![Twitch ColorChanger Logo](logo.webp)

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)
[![Code Quality](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/code-quality.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/code-quality.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Multi--Platform-blue.svg)](https://hub.docker.com/r/damastah/twitch-colorchanger)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)
[![Twitch](https://img.shields.io/badge/Twitch-Bot-purple.svg)](https://dev.twitch.tv/)
![EventSub](https://img.shields.io/badge/Chat-EventSub-blue.svg)
![Multi-User](https://img.shields.io/badge/Multi--User-Supported-brightgreen.svg)
![Auto-Token](https://img.shields.io/badge/Token%20Setup-Automatic-orange.svg)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/realabitbol)

Automatically change your Twitch username color after each message you send in chat. Supports both preset Twitch colors and random hex colors (for Prime/Turbo users). **Supports multiple users and Docker deployment!**

## Table of Contents

- [Features](#features)
  - [Core Features](#core-features)
  - [Additional Features](#additional-features)
- [Requirements](#requirements)
  - [Dependencies](#dependencies)
- [Quick Start](#quick-start)
  - [1. Get Twitch Credentials](#1-get-twitch-credentials)
    - [Create a Twitch App](#create-a-twitch-app)
    - [Generate Tokens](#generate-tokens)
  - [2. Run the Bot](#2-run-the-bot)
    - [Option A: Easy Startup Scripts (Recommended)](#option-a-easy-startup-scripts-recommended)
    - [Option B: Direct Run](#option-b-direct-run)
    - [Option C: Docker](#option-c-docker)
- [Usage](#usage)
  - [Local Development](#local-development)
  - [Runtime Chat Commands](#runtime-chat-commands)
  - [Docker Deployment](#docker-deployment)
    - [Build Locally](#build-locally)
    - [Pre-built Images](#pre-built-images)
    - [Docker Compose](#docker-compose)
- [Configuration](#configuration)
  - [Configuration File](#configuration-file)
  - [⚠️ Important: Channel List Configuration](#️-important-channel-list-configuration)
  - [Token Management Features](#token-management-features)
  - [Configuration Features](#configuration-features)
  - [Advanced Configuration](#advanced-configuration)
    - [General Environment Variables](#general-environment-variables)
    - [Internal Configuration Constants](#internal-configuration-constants)
    - [Environment Variable Usage Examples](#environment-variable-usage-examples)
    - [Chat Integration](#chat-integration)
- [Troubleshooting](#troubleshooting)
  - [Startup Script Issues](#startup-script-issues)
  - [Configuration Issues](#configuration-issues)
  - [Channel Configuration Issues](#channel-configuration-issues)
  - [Authentication Issues](#authentication-issues)
  - [Docker Issues](#docker-issues)
  - [Turbo/Prime Limitations](#turboprime-limitations)
  - [API Issues](#api-issues)
  - [Logging & Debugging](#logging--debugging)
- [Contributing](#contributing)
- [License](#license)
  - [Why GPL v3?](#why-gpl-v3)
- [⭐ Show Your Support](#-show-your-support)
  - [⭐ Star the Repository](#-star-the-repository)
  - [☕ Buy Me a Coffee](#-buy-me-a-coffee)
  - [Why support this project?](#why-support-this-project)

---

## Features

### Core Features

- **🎨 Dynamic Color Changes**: Automatically changes your Twitch chat color after every message
- **👥 Multi-User Support**: Run multiple bots for different Twitch accounts simultaneously
- **🎲 Flexible Colors**: Supports both preset Twitch colors and random hex colors (Prime/Turbo users)
- **🔌 Modern Chat Backend**: Uses EventSub WebSocket for reliable, modern chat connectivity.
- **🔑 Automatic Token Setup**: Smart token management with automatic authorization flow - just provide client credentials!
- **🔄 Token Refresh**: Automatic token validation and refresh with fallback to authorization flow when needed
- **🐳 Docker Ready**: Multi-platform support (amd64, arm64, arm/v7, arm/v6)
- **💾 Persistent Config**: Interactive setup with configuration file persistence
- **🟢 Runtime Toggle**: Enable/disable automatic color changes live with simple chat commands

### Additional Features

- **🛡️ Error Handling**: Automatic retries with exponential backoff
- **🎯 Smart Turbo/Prime Detection**: Automatically detects non-Turbo/Prime users and falls back to preset colors
- **💾 Persistent Fallback**: Saves Turbo/Prime limitations to config for permanent fallback behavior
- **⚡ Unattended Operation**: No user interaction required after initial authorization
- **✅ Configuration Validation**: Comprehensive validation with detailed error reporting
- **🛑 Per-User Disable Switch**: Temporarily pause color cycling without editing files or restarting

---

## Requirements

- **Python 3.13+** (tested with Python 3.13.7)
- **Docker** (optional, for containerized deployment)
- **Twitch Account** with Prime/Turbo subscription (for hex colors) or regular account (for preset colors)

### Dependencies

The bot requires minimal dependencies for optimal performance:

- **Core**: `aiohttp>=3.12.0,<4.0.0` - Async HTTP client for Twitch API communication

All dependencies are automatically installed via `requirements.txt`.

---

## Quick Start

### 1. Get Twitch Credentials

#### Create a Twitch App

1. Go to [Twitch Dev Console](https://dev.twitch.tv/console/apps) and sign in
2. Click **Register Your Application**
3. Name your app (e.g., `TwitchColorBot`)
4. Set **OAuth Redirect URLs** to: `https://localhost` (or any valid URL - not used for automatic setup)
5. Set **Category** to `Chat Bot` or `Other`
6. Click **Create** and copy your **Client ID**
7. Click **Manage** → **New Secret** to generate a **Client Secret**

> **Note**: For automatic setup (Option 1), the redirect URL is not used since we use device flow. For manual setup (Option 2), you'll need `https://twitchtokengenerator.com`.

#### Generate Tokens

##### Option 1: Automatic Setup (Recommended)

The bot can automatically generate tokens for you! Just provide your `client_id` and `client_secret` in the config file, and the bot will handle the rest:

1. Create your config file with client credentials and channels:

```json
{
  "users": [
    {
      "username": "your_username",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["your_channel"],
      "is_prime_or_turbo": true
    }
  ]
}
```

1. Run the bot - it will automatically prompt for authorization when needed
1. Follow the displayed URL and enter the code
1. Bot continues automatically once authorized

##### Option 2: Manual Token Generation

Use [twitchtokengenerator.com](https://twitchtokengenerator.com):

> **Important**: If using this method, make sure your Twitch app's OAuth Redirect URL is set to `https://twitchtokengenerator.com`

- Enter your Client ID and Client Secret
- Select scopes: `chat:read`, `user:read:chat`, `user:manage:chat_color` (optional: `chat:edit`)
- Click **Generate Token** and save the **Access Token** and **Refresh Token**

### 2. Run the Bot

#### Option A: Easy Startup Scripts (Recommended)

For the easiest setup, use the provided startup scripts that handle dependency installation and error checking:

**Windows:**

```cmd
start_bot.bat
```

**macOS/Linux:**

```bash
./start_bot.sh
```

These scripts will:

- Check if Python is installed and version compatible
- Verify your config file exists
- Install/update dependencies automatically
- Start the bot with proper error handling
- Keep the window open if there are errors

#### Option B: Direct Run

Create a config file from the sample:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
# Edit the config file with your credentials
python -m src.main
```

#### Option C: Docker

Create a config file from the sample:

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
# Edit the config file with your credentials
```

Then run:

```bash
# Prepare config directory (includes backups & cache files)
mkdir -p config
cp twitch_colorchanger.conf.sample config/twitch_colorchanger.conf

# Docker Hub
docker run -it --rm \
  -v $(pwd)/config:/app/config \
  damastah/twitch-colorchanger:latest

# Or GitHub Container Registry
docker run -it --rm \
  -v $(pwd)/config:/app/config \
  ghcr.io/realabitbol/twitch-colorchanger:latest
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
python -m src.main
```

### Runtime Chat Commands

Control a bot from any joined channel using messages sent by the bot's own account (other users are ignored):

| Command | Action |
|---------|--------|
| `ccd`   | Disable automatic color changes (persists) |
| `cce`   | Enable automatic color changes (persists)  |
| `ccc <color>` | Immediately set color to a specific value (works even when auto is disabled). `<color>` may be a Twitch preset (case-insensitive, e.g., `red`, `Sea_Green`) or a hex color with or without `#` (e.g., `#a1b2c3`, `ABC` which expands to `#aabbcc`). |

Behavior:

- Persists by updating the per-user `enabled` field in the config file
- Survives restarts (state restored on load)
- Only reacts to the bot user's own messages
- Disabling pauses API color calls but keeps all connections and stats active
- `ccc <color>` bypasses the enable/disable toggle and always attempts a change

Examples:

- `cce` - Enable automatic color changes
- `ccd` - Disable automatic color changes
- `ccc red` - Set color to Twitch preset "red"
- `ccc #ff0000` - Set color to hex red (Prime/Turbo users only)
- `ccc ABC` - Set color to hex #aabbcc (Prime/Turbo users only)
- `ccc nonsense` - Invalid argument, logs info message and no action taken
- `ccc #abcdef` - For non-Prime users, hex colors are ignored with info log

Tip: Use `DEBUG=true` to see log messages about auto color enable/disable status.

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

> **Note**: Both registries contain identical images. Choose based on your preference or organizational requirements.

**Image Details:**

- **Base Image**: Python Alpine Linux for maximum security and minimal attack surface
- **Optimized Size**: Significantly smaller than standard Python images (~50MB vs ~300MB)
- **Security Focused**: Alpine's security-oriented design with reduced package footprint
- **Production Ready**: Runs as non-root user (`appuser`) for enhanced container security

**Supported Architectures:**

- `linux/amd64` - Standard x86_64 (Intel/AMD)
- `linux/arm64` - ARM 64-bit (Apple Silicon, modern ARM servers)
- `linux/arm/v7` - ARM 32-bit (Raspberry Pi 2/3/4)
- `linux/arm/v6` - ARM v6 (Raspberry Pi Zero/1)

#### Docker Compose

Copy `docker-compose.yml-sample` to `docker-compose.yml` and customize:

```yaml
services:
  twitch-colorchanger:
    # Use either Docker Hub or GitHub Container Registry
    image: damastah/twitch-colorchanger:latest
    # Alternative: image: ghcr.io/realabitbol/twitch_colorchanger:latest
    volumes:
      - ./config:/app/config
    restart: unless-stopped
```

**Environment Variables in Docker:**

You can override any configuration constant using environment variables:

```bash
# Single environment override (Docker Hub)
docker run -e CONFIG_SAVE_TIMEOUT=5.0 \
  -v $(pwd)/config:/app/config \
  damastah/twitch-colorchanger:latest

# Multiple environment overrides (GitHub Container Registry)
docker run \
  -e CONFIG_SAVE_TIMEOUT=5.0 \
  -e RELOAD_WATCH_DELAY=1.0 \
  -v $(pwd)/config:/app/config \
  ghcr.io/realabitbol/twitch-colorchanger:latest
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
python -m src.main

# Or for Docker
docker run -e TWITCH_CONF_FILE=/app/config/my-config.conf \
  -v $(pwd)/my-config.conf:/app/config/my-config.conf \
  damastah/twitch-colorchanger:latest
```

Configuration file format:

**Minimal Configuration (Recommended):**

```json
{
  "users": [
    {
      "username": "your_username",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["your_channel"],
      "is_prime_or_turbo": true
    }
  ]
}
```

**Multi-User Configuration:**

```json
{
  "users": [
    {
      "username": "user1",
      "client_id": "client_id_1",
      "client_secret": "client_secret_1",
      "channels": ["channel1", "channel2"],
      "is_prime_or_turbo": true
    },
    {
      "username": "user2",
      "client_id": "client_id_2",
      "client_secret": "client_secret_2",
      "channels": ["channel3"],
      "is_prime_or_turbo": false
    }
  ]
}
```

### ⚠️ Important: Channel List Configuration

**The `channels` array is mandatory and critical for bot functionality:**

- **Message Tracking**: The bot can only detect your messages in channels it's connected to
- **Global Color Change**: While color changes apply to your entire Twitch account, the bot needs to see your messages to trigger the color changes
- **Channel Specificity**: The bot cannot monitor messages you send to channels not in your `channels` list
- **Multiple Channels**: Add all channels where you want the bot to detect your messages and trigger color changes

**Examples:**

```json
"channels": ["your_channel", "popular_streamer", "friend_channel"]
```

**Best Practice**: Include your own channel and any channels where you frequently chat to ensure comprehensive color change coverage.

### Enabled Flag (`enabled`)

Optional per-user switch:

```json
"enabled": true
```

Behavior:

- Omitted → defaults to `true` (feature active)
- `false` → bot connects but skips color change calls until re-enabled
- Toggled via `ccd` / `cce` (writes back asynchronously)

Use this to pause during events or testing without altering other users.
See [Runtime Chat Commands](#runtime-chat-commands) for in-chat toggles (`ccd` / `cce`).

### Token Management Features

- **🔄 Automatic Authorization**: Missing or invalid tokens trigger automatic device flow authorization
- **🔑 Smart Token Validation**: Checks existing tokens on startup and validates/refreshes as needed
- **💾 Persistent Token Storage**: Successfully authorized tokens are automatically saved to config
- **🛡️ Fallback Handling**: Seamlessly falls back to device flow when refresh tokens fail
- **Stateful Disable Switch**: `enabled` flag respected across all persistence operations
- **⚡ Unattended Operation**: No user interaction required after initial authorization

### Configuration Features

- **Multi-user support**: Add multiple users to the same config file
- **Simple configuration**: Single configuration file for all settings
- **Custom config file**: Use `TWITCH_CONF_FILE` environment variable to specify custom config file path
- **Docker support**: Containerized deployment with mounted config file

### Advanced Configuration

The bot supports extensive configuration through environment variables, allowing you to customize behavior without modifying the source code.

#### General Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug logging | `false` |
| `TWITCH_CONF_FILE` | Path to configuration file | `twitch_colorchanger.conf` |
| `TWITCH_BROADCASTER_CACHE` | Path to broadcaster ID cache file | `broadcaster_ids.cache.json` |

#### Internal Configuration Constants

All internal timing and behavior constants can be overridden via environment variables:

**EventSub Configuration:**

| Variable | Description | Default |
|----------|-------------|---------|
| `EVENTSUB_WS_URL` | WebSocket URL for EventSub connection | `wss://eventsub.wss.twitch.tv/ws` |
| `EVENTSUB_SUBSCRIPTIONS` | API endpoint for subscription management | `eventsub/subscriptions` |
| `EVENTSUB_CHAT_MESSAGE` | Event type for chat message subscriptions | `channel.chat.message` |

**Configuration Management:**

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_SAVE_TIMEOUT` | Max time to wait for config save completion | 10.0 |
| `CONFIG_WRITE_DEBOUNCE` | Delay after save for watcher resume | 0.5 |
| `RELOAD_WATCH_DELAY` | Delay after config reload before resuming watch | 2.0 |

**Exponential Backoff:**

| Variable | Description | Default |
|----------|-------------|---------|
| `BACKOFF_BASE_DELAY` | Base delay for exponential backoff | 1.0 |
| `BACKOFF_MAX_DELAY` | Maximum delay for exponential backoff | 300.0 |
| `BACKOFF_MULTIPLIER` | Multiplier for exponential backoff | 2.0 |
| `BACKOFF_JITTER_FACTOR` | Jitter factor to avoid thundering herd | 0.1 |

#### Environment Variable Usage Examples

Faster response times for stable networks:

```bash
export CONFIG_SAVE_TIMEOUT=5.0           # 5 seconds instead of 10
export RELOAD_WATCH_DELAY=1.0            # 1 second instead of 2
python -m src.main
```

Docker usage with environment overrides:

```bash
docker run -e CONFIG_SAVE_TIMEOUT=5.0 \
           damastah/twitch-colorchanger:latest
```

Error handling: Invalid values show warnings and fall back to defaults:

```bash
export CONFIG_SAVE_TIMEOUT=invalid
python -m src.main
# Output: Warning: Invalid float value for CONFIG_SAVE_TIMEOUT='invalid', using default 10.0
```

#### Chat Integration

The bot uses EventSub WebSocket for reliable chat connectivity. It automatically subscribes to `channel.chat.message` events filtered to messages from the bot user only, ensuring efficient and targeted message detection.

Required scopes (automatically requested during device flow):

| Purpose | Scope |
|---------|-------|
| Receive self chat messages over EventSub | `user:read:chat` |
| Change chat color via Helix | `user:manage:chat_color` |

The bot handles connection management automatically with built-in reconnection logic. Channel names are resolved to broadcaster IDs and cached for performance. The cache is persisted relative to the current working directory by default. For Docker deployments, both `TWITCH_CONF_FILE` and `TWITCH_BROADCASTER_CACHE` should be set to absolute paths in the mounted volume to ensure persistence across container restarts. If EventSub fails to initialize, the bot will log the failure and stop for that user.

---

## Troubleshooting

### Startup Script Issues

**Windows (`start_bot.bat`):**

- If you get "Python is not installed", install Python from [python.org](https://python.org) and make sure "Add to PATH" is checked
- If you get permission errors, run Command Prompt as Administrator
- For dependency installation issues, the script will automatically create a virtual environment

**macOS/Linux (`start_bot.sh`):**

- If you get "Permission denied", run: `chmod +x start_bot.sh`
- If Python version is too old, update using your package manager (brew, apt, yum, etc.)
- The script handles externally-managed environments by creating a virtual environment automatically

### Configuration Issues

**"Configuration file not found":**

```bash
cp twitch_colorchanger.conf.sample twitch_colorchanger.conf
```

**"Bot exits immediately":**

- Check your Client ID and Client Secret are correct
- Ensure you have the required scopes: `chat:read`, `user:read:chat`, `user:manage:chat_color`
- Verify your config file is valid JSON

**Virtual Environment:**
If you prefer to manage your own virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate.bat
pip install -r requirements.txt
python -m src.main
```

### Channel Configuration Issues

**"Bot doesn't change colors when I chat":**

1. Confirm you didn't previously send `ccd` (check logs for messages about auto color being disabled)
2. Check the config shows `"enabled": true` for your user
3. Verify you are chatting in one of the configured `channels`
4. Inspect logs for rate limiting (429 events) or token refresh failures
5. Temporarily run with `DEBUG=true` to see detailed events

- **Missing channels**: The bot can only detect messages in channels listed in your `channels` array
- **Check your config**: Ensure the channel name matches exactly (case-sensitive)
- **Add missing channels**: Update your config file to include all channels where you want color changes

**Example fix:**

```json
{
  "users": [
    {
      "username": "your_username",
      "channels": ["your_channel", "streamer1", "streamer2"],
      // Add any channel where you want the bot to detect your messages
    }
  ]
}
```

**"Bot works in some channels but not others":**

- **Channel list verification**: Check that all desired channels are in your `channels` array
- **Spelling mistakes**: Verify channel names are spelled correctly (no # symbol needed)
- **Case sensitivity**: Channel names must match exactly: `"ForsenTV"` ≠ `"forsentv"`

**"Bot joins channels but never triggers":**

- **Message visibility**: The bot needs to see your messages to trigger color changes
- **Channel permissions**: Ensure the bot can read chat in those channels
- **Live config reload**: After adding channels, the bot will automatically restart and join new channels

### Command-Related Issues

**"Bot not responding to commands":**

- **Message sender**: Commands only work when sent by the bot's own account (other users are ignored)
- **Enabled state**: Check if automatic color changes are disabled (`ccd` command) - use `cce` to re-enable
- **Channel membership**: Ensure the bot is connected to the channel where you're sending commands
- **Command syntax**: Verify correct command format (e.g., `ccc red`, not `ccc red extra`)
- **Prime/Turbo restrictions**: Hex colors via `ccc` are ignored for non-Prime/Turbo users

### Authentication Issues

- **Missing scopes**: ensure tokens include `chat:read`, `user:read:chat`, and `user:manage:chat_color` (optional: `chat:edit`)
- **Invalid / expired tokens**: regenerate tokens at [twitchtokengenerator.com](https://twitchtokengenerator.com)
- **Client credentials mismatch**: verify Client ID and Secret match the generated tokens

### Docker Issues

- **Config not loading**: confirm config directory is mounted correctly `-v $(pwd)/config:/app/config`
- **Configuration issues**: check that your config file has valid JSON format and contains user configurations
- **Color not changing**: non‑Prime/Turbo accounts can only use preset colors

### Turbo/Prime Limitations

- **Automatic Detection**: The bot automatically detects when a user lacks Turbo/Prime subscription for hex colors
- **Smart Fallback**: Automatically switches to preset Twitch colors when hex colors fail
- **Persistent Settings**: Saves the fallback preference to config file to avoid repeated API errors
- **Seamless Operation**: Users continue receiving color changes without interruption

### API Issues

- **Network errors**: transient failures are retried automatically; persistent 401 means token refresh failed
- **Color change failures**: ensure your account has Prime/Turbo for hex colors or use preset colors

### Logging & Debugging

- Set `DEBUG=true` for verbose logs

If issues persist, open an issue with: platform, Python/Docker version, relevant log snippet (exclude tokens).

---

## Contributing

We welcome contributions!

### CI/CD Setup

For maintainers setting up GitHub Actions with full functionality, see [CI/CD Setup Guide](.github/CI_SETUP.md) for configuring:

- **Docker Hub Credentials**: For automatic Docker image builds and publishing
- **Safety API Key**: For comprehensive security vulnerability scanning

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

# Set up pre-commit hooks (recommended)
pre-commit install

# Format Python code with Ruff (ensure venv is activated)
.venv/bin/python -m ruff format .
# or: make ruff-format (recommended - uses correct venv automatically)

# Format Markdown files with mdformat (optional)
make md-format

# Run linting (includes Ruff, mypy, bandit)
make lint

# Check Markdown formatting (optional)
make md-check

# Run comprehensive Python quality checks
make check-all

# Run mdformat via pre-commit (manual)
pre-commit run mdformat --all-files
```

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

### Why GPL v3?

We chose GPL v3 to ensure this software remains free and open source. Any derivative works must also be open source under compatible licenses, fostering a community of shared improvements.

---

## ⭐ Show Your Support

If you found this project helpful, please consider showing your support!

### ⭐ Star the Repository

Your star helps others discover this tool and motivates us to continue improving it.

**[⭐ Click here to star this repository](https://github.com/realAbitbol/twitch_colorchanger)**

### ☕ Buy Me a Coffee

If this bot has saved you time or enhanced your Twitch experience, consider supporting the development with a coffee!

**[☕ Support on Ko-fi](https://ko-fi.com/realabitbol)**

### Why support this project?

- 🎨 **Unique functionality** - One of the few bots that automatically changes Twitch chat colors
- 👥 **Multi-user support** - Run multiple accounts simultaneously
- 🐳 **Docker ready** - Easy deployment with comprehensive platform support
- 📚 **Well documented** - Complete guides for users and developers
- 🛡️ **Actively maintained** - Regular updates and bug fixes

Thank you for using Twitch ColorChanger! 🎉
