"""
Configuration management for the Twitch Color Changer bot
"""

import os
import sys
import json
from .colors import bcolors
from .utils import print_log, process_channels
from .logger import logger
from .config_validator import validate_user_config as validate_user, validate_all_users

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


def _setup_config_directory(config_file):
    """Set up config directory with proper permissions"""
    config_dir = os.path.dirname(config_file)
    if config_dir and not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        # Try to set directory permissions if possible
        try:
            os.chmod(config_dir, 0o755)
        except PermissionError:
            pass  # Ignore permission errors on directories


def _fix_docker_ownership(config_dir, config_file):
    """Fix ownership for Docker environments running as non-root"""
    if os.path.exists(config_dir) and os.geteuid() != 0:
        try:
            # Try to change ownership of the config directory to current user
            current_uid = os.getuid()
            current_gid = os.getgid()
            os.chown(config_dir, current_uid, current_gid)
            # Also try to change ownership of existing config file
            if os.path.exists(config_file):
                os.chown(config_file, current_uid, current_gid)
        except OSError:
            pass  # Ignore if we can't change ownership (e.g., no permission)


def _set_file_permissions(config_file):
    """Set appropriate file permissions"""
    if os.path.exists(config_file):
        try:
            os.chmod(config_file, 0o644)
        except PermissionError:
            pass  # Ignore permission errors on existing files


def _log_save_operation(users, config_file):
    """Log the save operation details"""
    print_log(f"💾 Saving {len(users)} users to {config_file}", bcolors.OKBLUE, debug_only=True)
    for i, user in enumerate(users, 1):
        print_log(f"  User {i}: {user['username']} -> use_random_colors: {user.get('use_random_colors', 'MISSING_FIELD')}", bcolors.OKCYAN, debug_only=True)


def _log_debug_data(save_data):
    """Log debug information about the data being saved"""
    print_log("🔍 DEBUG: Exact JSON being written:", bcolors.HEADER, debug_only=True)
    print_log(json.dumps(save_data, indent=2), bcolors.OKCYAN, debug_only=True)


def _verify_saved_data(config_file):
    """Verify that the data was saved correctly"""
    try:
        with open(config_file, 'r') as f:
            verification_data = json.load(f)
        print_log(f"✅ VERIFICATION: File actually contains {len(verification_data.get('users', []))} users", bcolors.OKGREEN, debug_only=True)
        for i, user in enumerate(verification_data.get('users', []), 1):
            username = user.get('username', 'NO_USERNAME')
            use_random_colors = user.get('use_random_colors', 'MISSING_FIELD')
            print_log(f"  Verified User {i}: {username} -> use_random_colors: {use_random_colors}", bcolors.OKGREEN, debug_only=True)
    except Exception as verify_error:
        print_log(f"❌ VERIFICATION FAILED: {verify_error}", bcolors.FAIL, debug_only=True)


def save_users_to_config(users, config_file):
    """Save users to config file"""
    try:
        # Ensure all users have use_random_colors field before saving
        for user in users:
            if 'use_random_colors' not in user:
                user['use_random_colors'] = True  # Default value
                print_log(f"🔧 Added missing use_random_colors field for {user.get('username', 'Unknown')}: {user['use_random_colors']}", bcolors.OKBLUE, debug_only=True)
        
        # Set up directory and permissions
        _setup_config_directory(config_file)
        config_dir = os.path.dirname(config_file)
        _fix_docker_ownership(config_dir, config_file)
        _set_file_permissions(config_file)
        
        # Log operation
        _log_save_operation(users, config_file)
        
        # Prepare and save data
        save_data = {'users': users}
        _log_debug_data(save_data)
        
        with open(config_file, 'w') as f:
            json.dump(save_data, f, indent=2)
        print_log("💾 Configuration saved successfully", bcolors.OKGREEN)
        
        # Verify the save
        _verify_saved_data(config_file)
    except Exception as e:
        print_log(f"⚠️ Failed to save configuration: {e}", bcolors.FAIL)


def update_user_in_config(user_config, config_file):
    """Update a specific user's configuration in the config file"""
    try:
        users = load_users_from_config(config_file)
        updated = False
        
        # Ensure the user_config has use_random_colors field
        if 'use_random_colors' not in user_config:
            user_config['use_random_colors'] = True  # Default value
            print_log(f"🔧 Added missing use_random_colors field for {user_config.get('username', 'Unknown')}: {user_config['use_random_colors']}", bcolors.OKBLUE, debug_only=True)
        
        # Find and update existing user
        for i, user in enumerate(users):
            if user.get('username') == user_config['username']:
                # Merge new config with existing config to preserve all fields
                merged_config = user.copy()  # Start with existing config
                merged_config.update(user_config)  # Update with new values
                users[i] = merged_config
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


def disable_random_colors_for_user(username, config_file):
    """Disable random colors for a specific user due to Turbo/Prime requirement"""
    try:
        users = load_users_from_config(config_file)
        
        # Find and update the user
        for user in users:
            if user.get('username') == username:
                user['use_random_colors'] = False
                print_log(f"🔧 Disabled random colors for {username} (requires Turbo/Prime)", bcolors.WARNING)
                break
        else:
            # User not found in config - this shouldn't happen but handle gracefully
            print_log(f"⚠️ User {username} not found in config when trying to disable random colors", bcolors.WARNING)
            return False
        
        save_users_to_config(users, config_file)
        return True
    except Exception as e:
        print_log(f"⚠️ Failed to disable random colors for {username}: {e}", bcolors.FAIL)
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
        # Support documented VAR name TWITCH_USE_RANDOM_COLORS_{n} and legacy USE_RANDOM_COLORS_{n}
        use_random_colors_str = os.environ.get(
            f'TWITCH_USE_RANDOM_COLORS_{user_num}',
            os.environ.get(f'USE_RANDOM_COLORS_{user_num}', 'true')
        )
        use_random_colors = use_random_colors_str.lower() in ['true', '1', 'yes']
        
        print_log(f"🔍 User {user_num} ({username}): TWITCH_USE_RANDOM_COLORS_{user_num}={os.environ.get(f'TWITCH_USE_RANDOM_COLORS_{user_num}', 'NOT_SET')} -> use_random_colors={use_random_colors}", bcolors.OKCYAN, debug_only=True)
        
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
    """Validate that user configuration has required fields - Simplified version"""
    return validate_user(user_config)


def _validate_docker_users(users):
    """Validate Docker mode users and return valid ones"""
    # Use simplified validation
    valid_users = validate_all_users(users)
    
    if not valid_users:
        logger.error("No valid user configurations found!")
        sys.exit(1)
    
    logger.info(f"✅ Found {len(valid_users)} valid user configuration(s)")
    return valid_users


def _persist_docker_config(users, config_file):
    """Try to persist Docker configuration for token refresh"""
    try:
        print_log(f"🔄 Persisting Docker config with {len(users)} users", bcolors.OKBLUE, debug_only=True)
        for i, user in enumerate(users, 1):
            print_log(f"  Persisting User {i}: {user['username']} -> use_random_colors: {user.get('use_random_colors', True)}", bcolors.OKCYAN, debug_only=True)
        
        save_users_to_config(users, config_file)
        print_log(f"💾 Configuration backed up to {config_file} for token persistence", bcolors.OKBLUE, debug_only=True)
    except Exception as e:
        print_log(f"⚠️ Cannot persist tokens in Docker mode: {e}", bcolors.WARNING)
        print_log("🔄 Tokens will be refreshed but not saved between container restarts", bcolors.WARNING)


def _merge_config_with_env(config_users, env_users):
    """Merge config file users with env users.

    Precedence rules:
      - Auth fields (access_token, refresh_token, client_id, client_secret) prefer config file.
      - Non-sensitive runtime fields (channels, use_random_colors) prefer environment variables.
      - Users present only in one source are included as-is.
    """
    merged_users = []

    config_user_map = {user['username']: user for user in config_users}

    for user_index, env_user in enumerate(env_users, 1):
        username = env_user['username']
        if username in config_user_map:
            config_user = config_user_map[username]
            # Check if env explicitly set use_random_colors for this user number
            env_has_flag = any(
                f'{prefix}_{user_index}' in os.environ for prefix in [
                    'TWITCH_USE_RANDOM_COLORS', 'USE_RANDOM_COLORS'
                ]
            )
            merged_user = {
                'username': config_user.get('username', env_user.get('username')),
                'access_token': config_user.get('access_token', env_user.get('access_token', '')),
                'refresh_token': config_user.get('refresh_token', env_user.get('refresh_token', '')),
                'client_id': config_user.get('client_id', env_user.get('client_id', '')),
                'client_secret': config_user.get('client_secret', env_user.get('client_secret', '')),
                'channels': env_user.get('channels', config_user.get('channels', [username])),
                # Always use env value which includes proper defaults from get_docker_config
                'use_random_colors': env_user['use_random_colors']
            }
            if env_has_flag:
                print_log(f"🔄 Merged user {username}: env override use_random_colors={env_user['use_random_colors']}", bcolors.OKBLUE, debug_only=True)
            else:
                print_log(f"🔄 Merged user {username}: default use_random_colors={env_user['use_random_colors']} (no env var)", bcolors.OKBLUE, debug_only=True)
        else:
            merged_user = env_user.copy()
            print_log(f"➕ Added new user {username} from environment variables", bcolors.OKGREEN)
        merged_users.append(merged_user)

    env_usernames = {user['username'] for user in env_users}
    for config_user in config_users:
        if config_user['username'] not in env_usernames:
            # Ensure config-only users have use_random_colors field
            config_only_user = config_user.copy()
            if 'use_random_colors' not in config_only_user:
                config_only_user['use_random_colors'] = True  # Default value
            merged_users.append(config_only_user)
            print_log(f"📁 Kept existing user {config_user['username']} from config file", bcolors.OKCYAN)

    return merged_users


def _get_docker_configuration(config_file):
    """Handle Docker mode configuration - merge with existing config file if present"""
    print_log("🐳 Docker mode detected - checking for existing configuration", bcolors.OKBLUE)
    
    # First, try to load existing config file
    existing_users = load_users_from_config(config_file)
    env_users = get_docker_config()
    
    if not env_users:
        print_log("❌ No valid user configurations found in environment variables!", bcolors.FAIL)
        print_log("Please set TWITCH_USERNAME_1, TWITCH_ACCESS_TOKEN_1, etc.", bcolors.FAIL)
        sys.exit(1)
    
    # If config file exists, merge configurations prioritizing config file values
    if existing_users:
        print_log("📁 Found existing config file - merging with environment variables", bcolors.OKCYAN)
        merged_users = _merge_config_with_env(existing_users, env_users)
        valid_users = _validate_docker_users(merged_users)
    else:
        print_log("📄 No existing config file - using environment variables", bcolors.OKBLUE)
        valid_users = _validate_docker_users(env_users)
    
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
    
    try:
        new_user = prompt_for_user()
    except EOFError:
        print_log("⚠️ User input interrupted, returning existing configuration", bcolors.WARNING)
        return valid_users
    
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
    
    try:
        user_config = prompt_for_user()
    except EOFError:
        print_log("❌ Cannot create configuration without user input", bcolors.FAIL)
        sys.exit(1)
    
    if not validate_user_config(user_config):
        print_log(INVALID_CONFIG_MSG, bcolors.FAIL)
        sys.exit(1)
    
    save_users_to_config([user_config], config_file)
    print_log(f"💾 Configuration saved to {config_file}", bcolors.OKGREEN)
    return [user_config]


def _handle_existing_config(valid_users, config_file):
    """Handle existing configuration choices"""
    _display_existing_config(valid_users)
    
    try:
        choice = input("\n🤔 Use existing config? (y/n/add): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print_log("\n⚠️ Input interrupted, using existing configuration", bcolors.WARNING)
        return valid_users
    
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
    """Get configuration from config file first, then environment variables as fallback"""
    config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
    
    # Always try to load from config file first (source of truth)
    users = load_users_from_config(config_file)
    docker_env_present = os.environ.get('TWITCH_USERNAME_1') and os.environ.get('TWITCH_ACCESS_TOKEN_1')

    if docker_env_present:
        # In Docker mode we always merge so env can override non-sensitive fields
        return _get_docker_configuration(config_file)
    else:
        if users:
            print_log(f"📁 Loaded {len(users)} user(s) from {config_file}", bcolors.OKGREEN)
            valid_users = _validate_loaded_users(users)
            if valid_users:
                print_log("✅ Using configuration file (no env overrides detected)", bcolors.OKBLUE)
                return valid_users
        # Interactive fallback
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
