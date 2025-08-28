"""
Simple configuration validation for the Twitch Color Changer bot
"""

from .logger import logger


def validate_user_config(user_config):
    """Validate user configuration - returns True if valid"""
    
    # Required fields
    username = user_config.get('username', '').strip()
    if not username or len(username) < 3 or len(username) > 25:
        logger.error(f"Username must be 3-25 characters: '{username}'")
        return False
    
    # Basic token validation
    access_token = user_config.get('access_token', '').strip()
    if not access_token or len(access_token) < 20:
        logger.error(f"Access token too short for {username}")
        return False
    
    if access_token.lower() in ['test', 'placeholder', 'your_token_here', 'fake_token']:
        logger.error(f"Please use a real token for {username}")
        return False
    
    # Channels validation
    channels = user_config.get('channels', [])
    if not channels or not isinstance(channels, list):
        logger.error(f"Channels list required for {username}")
        return False
    
    for channel in channels:
        if not isinstance(channel, str) or len(channel.strip()) < 3:
            logger.error(f"Invalid channel name for {username}: '{channel}'")
            return False
    
    return True


def validate_all_users(users_config):
    """Validate all users - returns list of valid users"""
    if not users_config:
        logger.error("No users configured")
        return []
    
    valid_users = []
    usernames_seen = set()
    
    for user_config in users_config:
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
    
    if not valid_users:
        logger.error("No valid user configurations found!")
    
    return valid_users
