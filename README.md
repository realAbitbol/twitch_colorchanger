# Twitch ColorChanger

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)
[![Code Quality](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/code-quality.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/code-quality.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Multi--Platform-blue.svg)](https://hub.docker.com/r/damastah/twitch-colorchanger)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)
[![Twitch](https://img.shields.io/badge/Twitch-Bot-purple.svg)](https://dev.twitch.tv/)
![IRC](https://img.shields.io/badge/Protocol-IRC-green.svg)
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
  - [Docker Deployment](#docker-deployment)
    - [Build Locally](#build-locally)
    - [Pre-built Images](#pre-built-images)
    - [Docker Compose](#docker-compose)
- [Configuration](#configuration)
  - [Configuration File](#configuration-file)
  - [Token Management Features](#token-management-features)
  - [Configuration Features](#configuration-features)
  - [Advanced Configuration](#advanced-configuration)
    - [General Environment Variables](#general-environment-variables)
    - [Internal Configuration Constants](#internal-configuration-constants)
    - [Environment Variable Usage Examples](#environment-variable-usage-examples)
  - [Runtime Configuration Changes](#runtime-configuration-changes)
  - [Docker Configuration](#docker-configuration)
  - [Debug Mode](#debug-mode)
- [Troubleshooting](#troubleshooting)
  - [Startup Script Issues](#startup-script-issues)
  - [Configuration Issues](#configuration-issues)
  - [Authentication Issues](#authentication-issues)
  - [Docker Issues](#docker-issues)
  - [Turbo/Prime Limitations](#turboprime-limitations)
  - [Rate / API Issues](#rate--api-issues)
  - [Logging & Debugging](#logging--debugging)
- [Technical Documentation](#technical-documentation)
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
- **🔄 Universal Compatibility**: Works with Chatterino, web chat, or any IRC client
- **🔑 Automatic Token Setup**: Smart token management with automatic authorization flow - just provide client credentials!
- **🔄 Token Refresh**: Automatic token validation and refresh with fallback to authorization flow when needed
- **🐳 Docker Ready**: Multi-platform support (amd64, arm64, arm/v7, arm/v6, riscv64)
- **💾 Persistent Config**: Interactive setup with configuration file persistence
- **👀 Live Config Reload**: Automatically detects config file changes and restarts bots without manual intervention

### Additional Features

- **🏗️ Colored Logging**: Clean, colored console output for easy monitoring
- **🛡️ Error Handling**: Automatic retries with exponential backoff
- **🎯 Smart Turbo/Prime Detection**: Automatically detects non-Turbo/Prime users and falls back to preset colors
- **💾 Persistent Fallback**: Saves Turbo/Prime limitations to config for permanent fallback behavior
- **⚡ Unattended Operation**: No user interaction required after initial authorization
- **✅ Configuration Validation**: Comprehensive validation with detailed error reporting
- **📊 Rate Limiting**: Smart rate limiting with quota tracking and logging
- **🔗 IRC Health Monitoring**: Robust connection health tracking with automatic reconnection (600s ping intervals)
- **📡 Connection Visibility**: Real-time ping/pong monitoring for connection status transparency

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
4. Set **OAuth Redirect URLs** to: `https://localhost` (or any valid URL - not used for automatic setup)
5. Set **Category** to `Chat Bot` or `Other`
6. Click **Create** and copy your **Client ID**
7. Click **Manage** → **New Secret** to generate a **Client Secret**

> **Note**: For automatic setup (Option 1), the redirect URL is not used since we use device flow. For manual setup (Option 2), you'll need `https://twitchtokengenerator.com`.

#### Generate Tokens

##### Option 1: Automatic Setup (Recommended)

The bot can automatically generate tokens for you! Just provide your `client_id` and `client_secret` in the config file, and the bot will handle the rest:

1. Create your config file with just client credentials, the channel you want to monitor and if your user is prime/turbo or not:

```json
{
  "users": [
    {
      "username": "your_username",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["channel1", "channel2"],
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
- Select scopes: `chat:read`, `user:manage:chat_color` (optional: `chat:edit`)
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
python -m src.main
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

**Environment Variables in Docker:**

You can override any configuration constant using environment variables:

```bash
# Single environment override
docker run -e NETWORK_PARTITION_THRESHOLD=1800 \
  -v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf \
  damastah/twitch-colorchanger:latest

# Multiple environment overrides
docker run \
  -e NETWORK_PARTITION_THRESHOLD=1800 \
  -e CONFIG_SAVE_TIMEOUT=5.0 \
  -e DEFAULT_BUCKET_LIMIT=1000 \
  -v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf \
  damastah/twitch-colorchanger:latest
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

**Automatic Setup (Recommended):**

```json
{
  "users": [
    {
      "username": "your_username",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "channels": ["channel1", "channel2"],
      "is_prime_or_turbo": true
    }
  ]
}
```

**Manual Token Setup:**

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
      "is_prime_or_turbo": true
    }
  ]
}
```

### Token Management Features

- **🔄 Automatic Authorization**: Missing or invalid tokens trigger automatic device flow authorization
- **🔑 Smart Token Validation**: Checks existing tokens on startup and validates/refreshes as needed
- **💾 Persistent Token Storage**: Successfully authorized tokens are automatically saved to config
- **🛡️ Fallback Handling**: Seamlessly falls back to device flow when refresh tokens fail
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

#### Internal Configuration Constants

All internal timing and behavior constants can be overridden via environment variables:

**Network Configuration:**

| Variable | Description | Default |
|----------|-------------|---------|
| `PING_EXPECTED_INTERVAL` | IRC server ping expected every 10 minutes | 600 |
| `SERVER_ACTIVITY_TIMEOUT` | 5 minutes without any server activity | 300 |
| `CONNECTION_RETRY_TIMEOUT` | Give up on connection after 10 minutes | 600 |
| `NETWORK_PARTITION_THRESHOLD` | 15 minutes of no connectivity before declaring partition | 900 |
| `PARTIAL_CONNECTIVITY_THRESHOLD` | 3 minutes for partial connectivity detection | 180 |

**IRC Configuration:**

| Variable | Description | Default |
|----------|-------------|---------|
| `CHANNEL_JOIN_TIMEOUT` | Max wait for JOIN confirmation | 30 |
| `MAX_JOIN_ATTEMPTS` | Maximum join attempts before giving up | 2 |
| `RECONNECT_DELAY` | Base delay before reconnection | 2 |
| `ASYNC_IRC_READ_TIMEOUT` | Read timeout for async IRC operations | 1.0 |
| `ASYNC_IRC_CONNECT_TIMEOUT` | Connection timeout for async IRC | 15.0 |
| `ASYNC_IRC_JOIN_TIMEOUT` | Channel join timeout for async IRC | 30.0 |
| `ASYNC_IRC_RECONNECT_TIMEOUT` | Reconnection timeout for async IRC | 30.0 |

**Health Monitoring:**

| Variable | Description | Default |
|----------|-------------|---------|
| `HEALTH_MONITOR_INTERVAL` | Check bot health every 5 minutes | 300 |
| `TASK_WATCHDOG_INTERVAL` | Check specific task health every 2 minutes | 120 |

**Configuration Management:**

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_SAVE_TIMEOUT` | Max time to wait for config save completion | 10.0 |
| `CONFIG_WRITE_DEBOUNCE` | Delay after save for watcher resume | 0.5 |
| `RELOAD_WATCH_DELAY` | Delay after config reload before resuming watch | 2.0 |

**Rate Limiting:**

| Variable | Description | Default |
|----------|-------------|---------|
| `DEFAULT_BUCKET_LIMIT` | Default API request bucket size | 800 |
| `RATE_LIMIT_SAFETY_BUFFER` | Safety buffer for rate limiting | 5 |
| `STALE_BUCKET_AGE` | Age after which buckets are considered stale | 60 |

**Exponential Backoff:**

| Variable | Description | Default |
|----------|-------------|---------|
| `BACKOFF_BASE_DELAY` | Base delay for exponential backoff | 1.0 |
| `BACKOFF_MAX_DELAY` | Maximum delay for exponential backoff | 300.0 |
| `BACKOFF_MULTIPLIER` | Multiplier for exponential backoff | 2.0 |
| `BACKOFF_JITTER_FACTOR` | Jitter factor to avoid thundering herd | 0.1 |

#### Environment Variable Usage Examples

**Increase network resilience for unstable connections:**

```bash
export NETWORK_PARTITION_THRESHOLD=1800  # 30 minutes instead of 15
export PARTIAL_CONNECTIVITY_THRESHOLD=300  # 5 minutes instead of 3
export CONNECTION_RETRY_TIMEOUT=1200     # 20 minutes instead of 10
python -m src.main
```

**Faster response times for stable networks:**

```bash
export CONFIG_SAVE_TIMEOUT=5.0           # 5 seconds instead of 10
export RELOAD_WATCH_DELAY=1.0            # 1 second instead of 2
export HEALTH_MONITOR_INTERVAL=120       # 2 minutes instead of 5
python -m src.main
```

**Docker usage with environment overrides:**

```bash
docker run -e NETWORK_PARTITION_THRESHOLD=1800 \
           -e CONFIG_SAVE_TIMEOUT=5.0 \
           damastah/twitch-colorchanger:latest
```

**Error handling:** Invalid values show warnings and fall back to defaults:

```bash
export NETWORK_PARTITION_THRESHOLD=invalid
python -m src.main
# Output: Warning: Invalid integer value for NETWORK_PARTITION_THRESHOLD='invalid', using default 900
```

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

1. Start the bot: `python -m src.main`
2. Edit `twitch_colorchanger.conf` in your editor
3. Save the file - bots automatically restart with new config
4. Check the console output for restart confirmation

**Note:** Invalid configuration changes are ignored with warnings logged to console. Bot-initiated updates (like token refreshes) do not trigger restarts to prevent infinite loops.

### Docker Configuration

The container runs as a non-root user (`appuser`) for enhanced security. Mount your config file directly:

```bash
docker run -v $PWD/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf damastah/twitch-colorchanger:latest
```

**Important**: The config file must be readable and writable by the container for token management:

```bash
# Make config file accessible by container user (UID 1000)
chmod 666 twitch_colorchanger.conf
```

This allows the bot to:

- Read your configuration on startup
- Save new tokens from automatic authorization
- Update tokens during refresh operations

### Debug Mode

Enable detailed logging for troubleshooting:

```bash
# Local debugging
DEBUG=true python -m src.main

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
- Verify your OAuth Redirect URL is set to `https://twitchtokengenerator.com`
- Make sure you have the required scopes: `chat:read`, `user:manage:chat_color`

**Virtual Environment:**
If you prefer to manage your own virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate.bat
pip install -r requirements.txt
python -m src.main
```

### Authentication Issues

- **Missing scopes**: ensure tokens include `chat:read` and `user:manage:chat_color` (and optionally `chat:edit`)
- **Invalid / expired tokens**: regenerate tokens at [twitchtokengenerator.com](https://twitchtokengenerator.com)
- **Client credentials mismatch**: verify Client ID and Secret match the generated tokens

### Docker Issues

- **Config not loading**: confirm config file is mounted correctly `-v $(pwd)/twitch_colorchanger.conf:/app/config/twitch_colorchanger.conf`
- **Configuration issues**: check that your config file has valid JSON format and contains user configurations
- **Color not changing**: non‑Prime/Turbo accounts can only use preset colors

### Turbo/Prime Limitations

- **Automatic Detection**: The bot automatically detects when a user lacks Turbo/Prime subscription for hex colors
- **Smart Fallback**: Automatically switches to preset Twitch colors when hex colors fail
- **Persistent Settings**: Saves the fallback preference to config file to avoid repeated API errors
- **Seamless Operation**: Users continue receiving color changes without interruption

### Rate / API Issues

- **Too many requests**: Twitch may temporarily limit rapid color changes; the bot already spaces them—avoid manual spamming
- **Network errors**: transient failures are retried automatically; persistent 401 means token refresh failed (recreate tokens)

### Logging & Debugging

- Set `DEBUG=true` for verbose logs
- All logs are colored for easy reading

If issues persist, open an issue with: platform, Python/Docker version, relevant log snippet (exclude tokens).

---

## Technical Documentation

For developers and technical implementation details:

- **[FUNCTIONAL_DOCUMENTATION.md](FUNCTIONAL_DOCUMENTATION.md)** - Detailed feature specifications and behavior

---

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

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
- 🔄 **Live config reload** - No restarts needed for configuration changes
- 📚 **Well documented** - Complete guides for users and developers
- 🛡️ **Actively maintained** - Regular updates and bug fixes

Thank you for using Twitch ColorChanger! 🎉
