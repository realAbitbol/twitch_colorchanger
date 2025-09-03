"""General utility helper functions.

Moved from the legacy top-level ``utils.py`` module into the ``utils`` package
to avoid a name collision (module vs package) introduced during refactor.
"""

from __future__ import annotations

from project_logging.logger import logger

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
    logger.log_event("startup", "instructions_header")
    logger.log_event(
        "startup",
        "instructions_setup_step",
        step=1,
        text="Create a Twitch application: https://dev.twitch.tv/console/apps",
    )
    logger.log_event(
        "startup",
        "instructions_setup_step",
        step=2,
        text="Set OAuth Redirect URL to: https://twitchtokengenerator.com",
    )
    logger.log_event(
        "startup",
        "instructions_setup_step",
        step=3,
        text="Copy your Client ID and Client Secret",
    )

    logger.log_event("startup", "instructions_auto_section")
    logger.log_event(
        "startup",
        "instructions_point",
        text="Copy twitch_colorchanger.conf.sample to twitch_colorchanger.conf",
    )
    logger.log_event(
        "startup", "instructions_point", text="Add username, client_id, client_secret"
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Run the bot; it handles token authorization automatically",
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Follow displayed URL and enter the code when prompted",
    )

    logger.log_event("startup", "instructions_manual_section")
    logger.log_event(
        "startup",
        "instructions_point",
        text="Generate tokens: https://twitchtokengenerator.com",
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Select scopes: chat:read, user:manage:chat_color",
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Save Access & Refresh Tokens in config file",
    )

    logger.log_event("startup", "instructions_how_it_works")
    logger.log_event(
        "startup", "instructions_point", text="Monitors your chat messages"
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Changes username color after each message",
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Supports preset Twitch and random hex colors",
    )
    logger.log_event(
        "startup", "instructions_point", text="Handles multiple users simultaneously"
    )
    logger.log_event(
        "startup",
        "instructions_point",
        text="Auto-refreshes tokens to minimize re-authorization",
    )
    logger.log_event("startup", "instructions_security_notice")
