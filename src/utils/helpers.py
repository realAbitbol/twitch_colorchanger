"""General utility helper functions.

Moved from the legacy top-level ``utils.py`` module into the ``utils`` package
to avoid a name collision (module vs package) introduced during refactor.
"""

from __future__ import annotations

__all__ = ["format_duration", "emit_startup_instructions"]


def format_duration(total_seconds: int | float | None) -> str:
    """Return a human-friendly Hh Mm Ss string for a duration in seconds.

    Examples:
      65 -> "1m 5s"
      3605 -> "1h 5m 5s" (hours, minutes, seconds)
      59 -> "59s"
    """
    if total_seconds is None:
        return "unknown"
    seconds = int(total_seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m {sec}s"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes}m {sec}s"


def emit_startup_instructions() -> None:
    """Emit structured log events with startup guidance."""
    print("📘 Instructions")
    print(
        "🪜 Setup step 1: Create a Twitch application: https://dev.twitch.tv/console/apps"
    )
    print(
        "🪜 Setup step 2: Set OAuth Redirect URL to: https://twitchtokengenerator.com"
    )
    print("🪜 Setup step 3: Copy your Client ID and Client Secret")

    print("⚙️ Automatic configuration")
    print("👉 Copy twitch_colorchanger.conf.sample to twitch_colorchanger.conf")
    print("👉 Add username, client_id, client_secret")
    print("👉 Run the bot; it handles token authorization automatically")
    print("👉 Follow displayed URL and enter the code when prompted")

    print("📝 Manual configuration")
    print("👉 Generate tokens: https://twitchtokengenerator.com")
    print("👉 Select scopes: chat:read, user:manage:chat_color")
    print("👉 Save Access & Refresh Tokens in config file")

    print("ℹ️ Features")
    print("👉 Monitors your chat messages")
    print("👉 Changes username color after each message")
    print("👉 Supports preset Twitch and random hex colors")
    print("👉 Handles multiple users simultaneously")
    print("👉 Auto-refreshes tokens to minimize re-authorization")
    print("👉 type 'cdd' to disable or 'cce' to enable in any joined channel.")
    print(
        "🔒 Security notice : Remember to never share your client id, client secret or your tokens!"
    )
