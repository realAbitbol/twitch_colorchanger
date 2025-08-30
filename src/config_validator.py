"""
Simple configuration validation for the Twitch Color Changer bot
"""

from .logger import logger


def _validate_username(user_config):
    """Validate username field"""
    username_raw = user_config.get('username', '')
    username = str(username_raw).strip() if username_raw is not None else ''
    if not username or len(username) < 3 or len(username) > 25:
        logger.error(f"Username must be 3-25 characters: '{username}'")
        return False, username
    return True, username


def _validate_token_credentials(user_config, username):
    """Validate token and credentials"""
    access_token = user_config.get('access_token', '').strip()
    client_id = user_config.get('client_id', '').strip()
    client_secret = user_config.get('client_secret', '').strip()

    # Check if we have either valid access token OR client credentials
    has_token_with_length = access_token and len(access_token) >= 20
    has_client_credentials = client_id and client_secret and len(
        client_id) >= 10 and len(client_secret) >= 10

    # Check if token is a placeholder
    placeholder_tokens = [
        'test', 'placeholder', 'your_token_here', 'fake_token', 'example_token_twenty_chars']

    if has_token_with_length and access_token.lower() in placeholder_tokens:
        logger.error(f"Please use a real token for {username}")
        return False

    # Valid access token is one that meets length and is not a placeholder
    has_access_token = has_token_with_length and access_token.lower() not in placeholder_tokens

    if not has_access_token and not has_client_credentials:
        logger.error(
            f"User {username} needs either access_token OR (client_id + client_secret) for automatic setup")
        return False

    return True


def _validate_channels(user_config, username):
    """Validate channels list"""
    channels = user_config.get('channels', [])
    if not channels or not isinstance(channels, list):
        logger.error(f"Channels list required for {username}")
        return False

    for channel in channels:
        if not isinstance(channel, str) or len(channel.strip()) < 3:
            logger.error(f"Invalid channel name for {username}: '{channel}'")
            return False

    return True


def validate_user_config(user_config):
    """Validate user configuration - returns True if valid"""

    # Type check
    if not isinstance(user_config, dict):
        logger.error(f"User config must be a dict, got {type(user_config)}")
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
        logger.error("Users config must be a list")
        return False

    if not users_config:
        logger.error("No users configured")
        return False

    for user_config in users_config:
        if not isinstance(user_config, dict):
            logger.error(f"User config must be a dict, got {type(user_config)}")
            return False

        if not validate_user_config(user_config):
            username = user_config.get('username', 'Unknown')
            logger.warning(f"Skipping invalid config for {username}")
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
            logger.error(f"User config must be a dict, got {type(user_config)}")
            continue

        if validate_user_config(user_config):
            username = user_config.get('username', '').strip().lower()

            # Check for duplicates
            if username in usernames_seen:
                logger.warning(f"Duplicate username '{username}' - skipping")
                continue

            usernames_seen.add(username)
            valid_users.append(user_config)
        else:
            username = user_config.get('username', 'Unknown')
            logger.warning(f"Skipping invalid config for {username}")

    return valid_users
