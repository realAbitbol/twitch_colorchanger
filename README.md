
# Multi-User Twitch ColorChanger

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)

Automatically change your Twitch username color after each message you send in chat. Supports both preset Twitch colors and random hex colors (for Prime/Turbo users). **Now supports multiple users and Docker unattended mode!**

---

## 🎯 Features

- Changes your Twitch chat color after every message you send
- **Multi-user support** - run multiple bots for different Twitch accounts simultaneously
- Supports both preset Twitch colors and random hex colors
- Works with Chatterino, web chat, or any IRC client
- Automatic token refresh for seamless operation
- **Docker unattended mode** with environment variables
- Interactive setup with persistent configuration

---

## 📦 Dependencies

- Requires **Python 3.11+** (tested up to Python 3.13)
- **Core Dependencies:**
  - `requests` - HTTP requests and API communication
  - `aiohttp` - Async HTTP client for better performance
  - `twitchio` - Twitch IRC bot framework
- For Docker usage, you need Docker installed
- All dependencies are automatically installed via `requirements.txt`

---

## 🛠️ Setup

### 1. Create a Twitch App (one-time)

To enable automatic color changes, you need a Twitch Client ID and Client Secret:

1. Go to [Twitch Dev Console](https://dev.twitch.tv/console/apps) and sign in.
2. Click **Register Your Application**.
3. Name your app (e.g., `TwitchColorBot`).
4. Set **OAuth Redirect URLs** to: `https://twitchtokengenerator.com`
5. Set **Category** to `Chat Bot` or `Other`.
6. Click **Create**. Copy your **Client ID**.
7. Click **Manage** next to your app, then **New Secret** to generate a **Client Secret**. Save both.

### 2. Generate Tokens

Use [twitchtokengenerator.com](https://twitchtokengenerator.com) (Custom Token Generator):

- Enter your Client ID and Client Secret
- Select scopes: `chat:read`, `user:manage:chat_color` (`chat:edit` optional)
- Click **Generate Token** and save the **Access Token** and **Refresh Token**

---

## ⚡ Usage

### Single User (CLI)

```bash
python main.py
```

You will be prompted to add users. The bot supports:

- **File-based configuration persistence**: Tokens saved in `twitch_colorchanger.conf` for future runs
- **Multi-user interactive mode**: Add multiple users in single session
- **Automatic token refresh**: Access tokens are automatically refreshed and saved
- **Configuration management**: Load existing config or create new configuration

### Multi-User Docker (Unattended)

For **multiple users**, use numbered environment variables:

```bash
# User 1
TWITCH_USERNAME_1=user1
TWITCH_ACCESS_TOKEN_1=token1
TWITCH_REFRESH_TOKEN_1=refresh1
TWITCH_CLIENT_ID_1=client1
TWITCH_CLIENT_SECRET_1=secret1
TWITCH_CHANNELS_1=channel1,channel2
TWITCH_USE_RANDOM_COLORS_1=true

# User 2
TWITCH_USERNAME_2=user2
TWITCH_ACCESS_TOKEN_2=token2
TWITCH_REFRESH_TOKEN_2=refresh2
TWITCH_CLIENT_ID_2=client2
TWITCH_CLIENT_SECRET_2=secret2
TWITCH_CHANNELS_2=channel3,channel4
TWITCH_USE_RANDOM_COLORS_2=false

# Run with Docker
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

### Single User Docker

You can use the official image or build your own.

#### Build the Docker Image Locally

To build the image from source:

```bash
docker build -t twitch-colorchanger .
```

Then run it:

```bash
docker run -it --rm \
    -e TWITCH_USERNAME=your_twitch_username \
    -e TWITCH_ACCESS_TOKEN=your_access_token \
    -e TWITCH_REFRESH_TOKEN=your_refresh_token \
    -e TWITCH_CLIENT_ID=your_client_id \
    -e TWITCH_CLIENT_SECRET=your_client_secret \
    -e TWITCH_CHANNELS=channel1,channel2 \
    twitch-colorchanger
```

#### Using Prebuilt Image

Multi-platform images (x86_64, ARM64, ARMv7, ARMv6, RISC-V, MIPS64LE) are automatically built and published on every release to both Docker Hub and GitHub Container Registry.

**🔄 Token Persistence in Docker:**

- Tokens are automatically refreshed in Docker mode
- Mount a volume to persist config file between container restarts:

  ```bash
  docker run -it --rm \
      -v $(pwd)/config:/app/config \
      -e TWITCH_USERNAME_1=user1 \
      -e TWITCH_ACCESS_TOKEN_1=token1 \
      damastah/twitch-colorchanger:latest
  ```

- Config file is saved to `/app/config/twitch_colorchanger.conf` in the container

**From Docker Hub:**

```bash
docker run -it --rm \
    -e TWITCH_USERNAME=your_twitch_username \
    -e TWITCH_ACCESS_TOKEN=your_access_token \
    -e TWITCH_REFRESH_TOKEN=your_refresh_token \
    -e TWITCH_CLIENT_ID=your_client_id \
    -e TWITCH_CLIENT_SECRET=your_client_secret \
    -e TWITCH_CHANNELS=channel1,channel2 \
    damastah/twitch-colorchanger:latest
```

**From GitHub Container Registry:**

```bash
docker run -it --rm \
    -e TWITCH_USERNAME=your_twitch_username \
    -e TWITCH_ACCESS_TOKEN=your_access_token \
    -e TWITCH_REFRESH_TOKEN=your_refresh_token \
    -e TWITCH_CLIENT_ID=your_client_id \
    -e TWITCH_CLIENT_SECRET=your_client_secret \
    -e TWITCH_CHANNELS=channel1,channel2 \
    ghcr.io/realabitbol/twitch-colorchanger:latest
```

#### Using Docker Compose for Multi-User

See `docker-compose.yml-sample` for a template. Example for multiple users:

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
      
      # Optional settings
      - FORCE_COLOR=true
      - PYTHONUNBUFFERED=1
    volumes:
      - .:/app
    restart: unless-stopped
```

---

## ⚙️ Configuration

### Multi-User Configuration

You can configure the bot using environment variables (for Docker) or interactively (CLI):

**For multiple users in Docker**, use numbered environment variables:

- `TWITCH_USERNAME_1`, `TWITCH_USERNAME_2`, etc.: Twitch usernames
- `TWITCH_ACCESS_TOKEN_1`, `TWITCH_ACCESS_TOKEN_2`, etc.: OAuth access tokens
- `TWITCH_REFRESH_TOKEN_1`, `TWITCH_REFRESH_TOKEN_2`, etc.: OAuth refresh tokens
- `TWITCH_CLIENT_ID_1`, `TWITCH_CLIENT_ID_2`, etc.: Twitch app client IDs
- `TWITCH_CLIENT_SECRET_1`, `TWITCH_CLIENT_SECRET_2`, etc.: Twitch app client secrets
- `TWITCH_CHANNELS_1`, `TWITCH_CHANNELS_2`, etc.: Comma-separated list of channels
- `TWITCH_USE_RANDOM_COLORS_1`, `TWITCH_USE_RANDOM_COLORS_2`, etc.: `true` for random hex colors

### Single User Configuration (Legacy)

- `TWITCH_USERNAME`: Your Twitch username (single user mode)
- `TWITCH_ACCESS_TOKEN`: OAuth access token
- `TWITCH_REFRESH_TOKEN`: OAuth refresh token
- `TWITCH_CLIENT_ID`: Twitch app client ID
- `TWITCH_CLIENT_SECRET`: Twitch app client secret
- `TWITCH_CHANNELS`: Comma-separated list of channels to join
- `TWITCH_USE_RANDOM_COLORS`: `true` for random hex colors (Prime/Turbo only)
- `FORCE_COLOR`: `true` to force colored logs

Tokens and settings are saved in `twitch_colorchanger.conf` for future runs.

### Configuration File Format

The bot saves your settings in `twitch_colorchanger.conf` (JSON format) for automatic loading:

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

- **Automatic token refresh**: Tokens are refreshed and saved automatically (even in Docker mode)
- **Multi-user support**: Add multiple users to the same config file
- **Interactive management**: Choose to use existing config, add users, or create new
- **Environment override**: Use `TWITCH_CONF_FILE` to specify custom config file path
- **Connection keep-alive**: Handles Twitch ping-pong to maintain stable connections
- **Periodic token refresh**: Tokens are refreshed 1 hour before expiry to prevent interruptions

---

## 🐞 Troubleshooting

### General Issues

- **Missing scopes**: Make sure your token has `chat:read` and `user:manage:chat_color`.
- **Color not changing**: Prime/Turbo users can use random hex colors; others use preset Twitch colors.
- **Rate limits**: Twitch API allows color changes every ~1.5 seconds.
- **Docker issues**: Ensure environment variables are set and volume is mounted for config persistence.

### Multi-User Specific Issues

- **Only some users working**: Check that all numbered environment variables are set correctly for each user (e.g., `TWITCH_USERNAME_1`, `TWITCH_ACCESS_TOKEN_1`, etc.).
- **Users not detected**: Environment variable names must be exact - use `_1`, `_2`, `_3` etc. with no gaps in numbering.
- **Config file conflicts**: The multi-user config format uses `{"users": [...]}`. Legacy single-user configs are automatically converted.
- **Mixed environment and config**: Environment variables take precedence over config file settings.

### How Multi-User Detection Works

1. **Environment Mode**: If any `TWITCH_USERNAME_1` (or `TWITCH_USERNAME` for legacy) is found, environment mode is used
2. **Interactive Mode**: If no environment variables are set, the bot will load from config file and prompt for additional users
3. **Backwards Compatibility**: Legacy single-user environment variables (`TWITCH_USERNAME` without numbers) are still supported

---

## 🏗️ Architecture

This project uses a **modular architecture** for better maintainability and extensibility:

### Project Structure

```text
twitch_colorchanger/
├── main.py                 # Entry point for the application
├── src/                    # Core application modules
│   ├── __init__.py        # Package initialization
│   ├── colors.py          # Color definitions and utilities
│   ├── config.py          # Configuration management (env vars & interactive)
│   ├── utils.py           # Utility functions and logging
│   ├── bot.py             # TwitchColorBot class (core bot logic)
│   └── bot_manager.py     # Multi-bot management and orchestration
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container definition
└── docker-compose.yml-sample  # Docker Compose example
```

### Key Components

- **`main.py`**: Async entry point that coordinates configuration and bot execution
- **`src/config.py`**: Handles both environment variables (Docker mode) and interactive setup
- **`src/bot.py`**: Individual bot instance with color changing logic and token management
- **`src/bot_manager.py`**: Manages multiple bots, handles graceful shutdown, and aggregate statistics
- **`src/utils.py`**: Shared utilities for logging, user input, and channel processing
- **`src/colors.py`**: Color definitions, ANSI codes, and color generation functions

### Benefits

- **Maintainability**: Smaller, focused modules (50-150 lines each vs 726 lines monolith)
- **Extensibility**: Easy to add features without affecting other components
- **Testability**: Individual modules can be tested in isolation
- **Readability**: Clear separation of concerns and focused functionality

---

## 📄 License

This project is licensed under the GNU GPL v3. See `LICENSE` for details.
