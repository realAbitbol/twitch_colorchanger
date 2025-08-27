"""
Configuration management for the Twitch Color Changer bot
"""

import os
import sys
import json
from .colors import bcolors
from .utils import print_log, process_channels

# Constants for repeated messages
INVALID_CONFIG_MSG = "❌ Invalid configuration provided!"


def load_users_from_config(config_file):
    """Load users from config file"""
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
            # Support both new multi-user format and legacy single-user format
            if isinstance(data, dict) and 'users' in data:
                return data['users']
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'username' in data:
                # Legacy single-user format, convert to multi-user
                return [data]
            else:
                return []
    except FileNotFoundError:
        return []
    except Exception as e:
        print_log(f"⚠️ Error loading config: {e}", bcolors.FAIL)
        return []


def save_users_to_config(users, config_file):
    """Save users to config file"""
    try:
        with open(config_file, 'w') as f:
            json.dump({'users': users}, f, indent=2)
        print_log("💾 Configuration saved successfully", bcolors.OKGREEN, debug_only=True)
    except Exception as e:
        print_log(f"⚠️ Failed to save configuration: {e}", bcolors.FAIL)


def update_user_in_config(user_config, config_file):
    """Update a specific user's configuration in the config file"""
    try:
        users = load_users_from_config(config_file)
        updated = False
        
        # Find and update existing user
        for i, user in enumerate(users):
            if user.get('username') == user_config['username']:
                users[i] = user_config
                updated = True
                break
        
        # If user not found, add them
        if not updated:
            users.append(user_config)
        
        save_users_to_config(users, config_file)
        return True
    except Exception as e:
        print_log(f"⚠️ Failed to update user configuration: {e}", bcolors.FAIL)
        return False


def get_docker_config():
    """Extract configuration from environment variables for Docker deployment"""
    users = []
    user_num = 1
    
    while True:
        # Check if user exists (at minimum username and access token)
        username = os.environ.get(f'TWITCH_USERNAME_{user_num}')
        access_token = os.environ.get(f'TWITCH_ACCESS_TOKEN_{user_num}')
        
        if not username or not access_token:
            break
            
        # Get all user configuration
        refresh_token = os.environ.get(f'TWITCH_REFRESH_TOKEN_{user_num}', '')
        client_id = os.environ.get(f'TWITCH_CLIENT_ID_{user_num}', '')
        client_secret = os.environ.get(f'TWITCH_CLIENT_SECRET_{user_num}', '')
        channels_str = os.environ.get(f'TWITCH_CHANNELS_{user_num}', username)
        channels = process_channels(channels_str)
        use_random_colors_str = os.environ.get(f'USE_RANDOM_COLORS_{user_num}', 'true')
        use_random_colors = use_random_colors_str.lower() in ['true', '1', 'yes']
        
        user_config = {
            'username': username,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
            'channels': channels,
            'use_random_colors': use_random_colors
        }
        
        users.append(user_config)
        user_num += 1
        
        # Safety limit to prevent infinite loops
        if user_num > 99:
            break
    
    return users


def validate_user_config(user_config):
    """Validate that user configuration has required fields"""
    required_fields = ['username', 'access_token', 'channels']
    missing_fields = []
    
    for field in required_fields:
        if not user_config.get(field):
            missing_fields.append(field)
    
    if missing_fields:
        print_log(f"❌ Missing required fields for user {user_config.get('username', 'Unknown')}: {', '.join(missing_fields)}", bcolors.FAIL)
        return False
    
    if not user_config['channels']:
        print_log(f"❌ No channels specified for user {user_config['username']}", bcolors.FAIL)
        return False
    
    return True


def _validate_docker_users(users):
    """Validate Docker mode users and return valid ones"""
    valid_users = []
    for user_config in users:
        if validate_user_config(user_config):
            valid_users.append(user_config)
        else:
            print_log(f"⚠️ Skipping invalid configuration for user {user_config.get('username', 'Unknown')}", bcolors.WARNING)
    
    if not valid_users:
        print_log("❌ No valid user configurations found!", bcolors.FAIL)
        sys.exit(1)
    
    print_log(f"✅ Found {len(valid_users)} valid user configuration(s)", bcolors.OKGREEN)
    return valid_users


def _persist_docker_config(users, config_file):
    """Try to persist Docker configuration for token refresh"""
    try:
        save_users_to_config(users, config_file)
        print_log(f"💾 Docker configuration backed up to {config_file} for token persistence", bcolors.OKBLUE)
    except Exception as e:
        print_log(f"⚠️ Cannot persist tokens in Docker mode: {e}", bcolors.WARNING)
        print_log("🔄 Tokens will be refreshed but not saved between container restarts", bcolors.WARNING)


def _get_docker_configuration(config_file):
    """Handle Docker mode configuration"""
    print_log("🐳 Docker mode detected - using environment variables", bcolors.OKBLUE)
    users = get_docker_config()
    
    if not users:
        print_log("❌ No valid user configurations found in environment variables!", bcolors.FAIL)
        print_log("Please set TWITCH_USERNAME_1, TWITCH_ACCESS_TOKEN_1, etc.", bcolors.FAIL)
        sys.exit(1)
    
    valid_users = _validate_docker_users(users)
    _persist_docker_config(valid_users, config_file)
    return valid_users


def _validate_loaded_users(users):
    """Validate users loaded from config file"""
    valid_users = []
    for user_config in users:
        if validate_user_config(user_config):
            valid_users.append(user_config)
        else:
            print_log(f"⚠️ Invalid configuration for user {user_config.get('username', 'Unknown')}", bcolors.WARNING)
    return valid_users


def _display_existing_config(valid_users):
    """Display existing configuration to user"""
    print_log("\n📋 Existing configuration found:", bcolors.OKCYAN)
    for i, user in enumerate(valid_users, 1):
        print_log(f"  {i}. {user['username']} -> {', '.join(user['channels'])}")


def _add_new_user_to_config(valid_users, config_file):
    """Add a new user to existing configuration"""
    print_log("➕ Adding new user to existing configuration", bcolors.OKBLUE)
    from .utils import prompt_for_user
    new_user = prompt_for_user()
    
    if not validate_user_config(new_user):
        print_log(INVALID_CONFIG_MSG, bcolors.FAIL)
        sys.exit(1)
    
    valid_users.append(new_user)
    save_users_to_config(valid_users, config_file)
    return valid_users


def _create_new_configuration(config_file):
    """Create new configuration from user input"""
    print_log("🆕 Creating new configuration", bcolors.OKBLUE)
    from .utils import prompt_for_user
    user_config = prompt_for_user()
    
    if not validate_user_config(user_config):
        print_log(INVALID_CONFIG_MSG, bcolors.FAIL)
        sys.exit(1)
    
    save_users_to_config([user_config], config_file)
    print_log(f"💾 Configuration saved to {config_file}", bcolors.OKGREEN)
    return [user_config]


def _handle_existing_config(valid_users, config_file):
    """Handle existing configuration choices"""
    _display_existing_config(valid_users)
    choice = input("\n🤔 Use existing config? (y/n/add): ").strip().lower()
    
    if choice in ('y', 'yes'):
        return valid_users
    elif choice == 'add':
        return _add_new_user_to_config(valid_users, config_file)
    else:
        return _create_new_configuration(config_file)


def _get_interactive_configuration(config_file):
    """Handle interactive mode configuration"""
    print_log("💻 Interactive mode", bcolors.OKBLUE)
    users = load_users_from_config(config_file)
    
    if users:
        print_log(f"📁 Loaded {len(users)} user(s) from {config_file}", bcolors.OKGREEN)
        valid_users = _validate_loaded_users(users)
        
        if valid_users:
            return _handle_existing_config(valid_users, config_file)
    
    return _create_new_configuration(config_file)


def get_configuration():
    """Get configuration from environment variables, config file, or user input"""
    config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
    
    # Check if we're in Docker mode (environment variables present)
    if os.environ.get('TWITCH_USERNAME_1') and os.environ.get('TWITCH_ACCESS_TOKEN_1'):
        return _get_docker_configuration(config_file)
    else:
        return _get_interactive_configuration(config_file)


def print_config_summary(users):
    """Print a summary of the loaded configuration"""
    print_log("\n📊 Configuration Summary:", bcolors.HEADER)
    print_log(f"👥 Total Users: {len(users)}", bcolors.OKBLUE)
    
    for i, user in enumerate(users, 1):
        print_log(f"\n👤 User {i}:", bcolors.OKCYAN)
        print_log(f"   Username: {user['username']}")
        print_log(f"   Channels: {', '.join(user['channels'])}")
        print_log(f"   Random Colors: {'Yes' if user.get('use_random_colors', True) else 'No'}")
        print_log(f"   Has Refresh Token: {'Yes' if user.get('refresh_token') else 'No'}")
        print_log(f"   Has Client Credentials: {'Yes' if user.get('client_id') and user.get('client_secret') else 'No'}")
