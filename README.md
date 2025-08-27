
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

- Requires **Python 3.12+** (no external dependencies except the built-in `requests` library, which is installed automatically in Docker)
- No other packages required
- For Docker usage, you need Docker installed

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
python twitch_colorchanger.py
```

You will be prompted to add users. The bot supports:

- Adding multiple users interactively
- Tokens are saved in `twitch_colorchanger.conf` for future runs
- Each user can have different settings (channels, color preferences)

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

Multi-platform images (x86_64 and ARM64) are automatically built and published on every release to both Docker Hub and GitHub Container Registry.

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

## 📄 License

This project is licensed under the GNU GPL v3. See `LICENSE` for details.
