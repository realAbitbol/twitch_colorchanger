"""
Simple configuration validation for the Twitch Color Changer bot
"""

import logging

from .logger import logger


def _validate_username(user_config):
    """Validate username field"""
    username_raw = user_config.get("username", "")
    username = str(username_raw).strip() if username_raw is not None else ""
    if not username or len(username) < 3 or len(username) > 25:
        logger.log_event(
            "validation",
            "username_invalid",
            level=logging.ERROR,
            username=username,
        )
        return False, username
    return True, username


def _validate_token_credentials(user_config, username):
    """Validate token and credentials"""
    access_token = user_config.get("access_token", "").strip()
    client_id = user_config.get("client_id", "").strip()
    client_secret = user_config.get("client_secret", "").strip()

    # Check if we have either valid access token OR client credentials
    has_token_with_length = access_token and len(access_token) >= 20
    has_client_credentials = (
        client_id
        and client_secret
        and len(client_id) >= 10
        and len(client_secret) >= 10
    )

    # Check if token is a placeholder
    placeholder_tokens = [
        "test",
        "placeholder",
        "your_token_here",
        "fake_token",
        "example_token_twenty_chars",
    ]

    if has_token_with_length and access_token.lower() in placeholder_tokens:
        logger.log_event(
            "validation",
            "placeholder_token",
            level=logging.ERROR,
            username=username,
        )
        return False

    # Valid access token is one that meets length and is not a placeholder
    has_access_token = (
        has_token_with_length and access_token.lower() not in placeholder_tokens
    )

    if not has_access_token and not has_client_credentials:
        logger.log_event(
            "validation",
            "missing_auth",
            level=logging.ERROR,
            username=username,
        )
        return False

    return True


def _validate_channels(user_config, username):
    """Validate channels list"""
    channels = user_config.get("channels", [])
    if not channels or not isinstance(channels, list):
        logger.log_event(
            "validation",
            "channels_missing",
            level=logging.ERROR,
            username=username,
        )
        return False

    for channel in channels:
        if not isinstance(channel, str) or len(channel.strip()) < 3:
            logger.log_event(
                "validation",
                "channel_invalid",
                level=logging.ERROR,
                username=username,
                channel=channel,
            )
            return False

    return True


def validate_user_config(user_config):
    """Validate user configuration - returns True if valid"""

    # Type check
    if not isinstance(user_config, dict):
        logger.log_event(
            "validation",
            "user_config_not_dict",
            level=logging.ERROR,
            type=str(type(user_config)),
        )
        return False

    # Validate username
    username_valid, username = _validate_username(user_config)
    if not username_valid:
        return False

    # Validate token/credentials
    if not _validate_token_credentials(user_config, username):
        return False

    # Validate channels
    if not _validate_channels(user_config, username):
        return False

    return True


def validate_all_users(users_config):
    """Validate all users - returns True if ALL users are valid, False otherwise"""
    if not isinstance(users_config, list):
        logger.log_event("validation", "users_not_list", level=logging.ERROR)
        return False

    if not users_config:
        logger.log_event("validation", "no_users", level=logging.ERROR)
        return False

    for user_config in users_config:
        if not isinstance(user_config, dict):
            logger.log_event(
                "validation",
                "user_config_not_dict",
                level=logging.ERROR,
                type=str(type(user_config)),
            )
            return False

        if not validate_user_config(user_config):
            username = user_config.get("username", "Unknown")
            logger.log_event(
                "validation",
                "user_invalid_skipped",
                level=logging.WARNING,
                username=username,
            )
            return False

    return True


def get_valid_users(users_config):
    """Get list of valid users from config"""
    if not isinstance(users_config, list):
        return []

    if not users_config:
        return []

    valid_users = []
    usernames_seen = set()

    for user_config in users_config:
        if not isinstance(user_config, dict):
            logger.log_event(
                "validation",
                "user_config_not_dict",
                level=logging.ERROR,
                type=str(type(user_config)),
            )
            continue

        if validate_user_config(user_config):
            username = user_config.get("username", "").strip().lower()

            # Check for duplicates
            if username in usernames_seen:
                logger.log_event(
                    "validation",
                    "duplicate_username",
                    level=logging.WARNING,
                    username=username,
                )
                continue

            usernames_seen.add(username)
            valid_users.append(user_config)
        else:
            username = user_config.get("username", "Unknown")
            logger.log_event(
                "validation",
                "user_invalid_skipped",
                level=logging.WARNING,
                username=username,
            )

    return valid_users
