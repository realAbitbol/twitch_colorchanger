
# Twitch ColorChanger

[![Build and Push Docker Images](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml/badge.svg)](https://github.com/realAbitbol/twitch_colorchanger/actions/workflows/docker-build.yml)

Automatically change your Twitch username color after each message you send in chat. Supports both preset Twitch colors and random hex colors (for Prime/Turbo users).

---

## � Features

- Changes your Twitch chat color after every message you send
- Supports both preset Twitch colors and random hex colors
- Works with Chatterino, web chat, or any IRC client
- Automatic token refresh for seamless operation
- Docker support for unattended operation

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

### Run in CLI

```bash
python twitch_colorchanger.py
```

You will be prompted for your Twitch credentials and channels to join. Tokens are saved in `twitch_colorchanger.conf` for future runs.

### Run with Docker

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

#### Using Docker Compose

See `docker-compose.yml-sample` for a template. Example:

```yaml
services:
    twitch-colorchanger:
        # Use either Docker Hub or GitHub Container Registry
        image: damastah/twitch-colorchanger:latest
        # image: ghcr.io/realabitbol/twitch-colorchanger:latest
        environment:
            - TWITCH_USERNAME=your_twitch_username
            - TWITCH_ACCESS_TOKEN=your_access_token
            - TWITCH_REFRESH_TOKEN=your_refresh_token
            - TWITCH_CLIENT_ID=your_client_id
            - TWITCH_CLIENT_SECRET=your_client_secret
            - TWITCH_CHANNELS=channel1,channel2
            - TWITCH_USE_RANDOM_COLORS=true
            - FORCE_COLOR=true
            - PYTHONUNBUFFERED=1
        volumes:
            - .:/app
        restart: unless-stopped
```

---

## ⚙️ Configuration

You can configure the bot using environment variables (for Docker) or interactively (CLI):

- `TWITCH_USERNAME`: Your Twitch username
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

- **Missing scopes**: Make sure your token has `chat:read` and `user:manage:chat_color`.
- **Color not changing**: Prime/Turbo users can use random hex colors; others use preset Twitch colors.
- **Rate limits**: Twitch API allows color changes every ~1.5 seconds.
- **Docker issues**: Ensure environment variables are set and volume is mounted for config persistence.

---

## 📄 License

This project is licensed under the GNU GPL v3. See `LICENSE` for details.
