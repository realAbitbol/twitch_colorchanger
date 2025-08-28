"""
Configuration management for the Twitch Color Changer bot
"""

import os
import sys
import json
from .colors import bcolors
from .utils import print_log
from .logger import logger
from .config_validator import validate_user_config as validate_user, validate_all_users

# Constants for repeated messages


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



def validate_user_config(user_config):
    """Validate that user configuration has required fields - Simplified version"""
    return validate_user(user_config)


def get_configuration():
    """Get configuration from config file only"""
    config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
    
    # Load configuration from file
    users = load_users_from_config(config_file)
    
    if not users:
        print_log("❌ No configuration file found!", bcolors.FAIL)
        print_log(f"Please create a config file: {config_file}", bcolors.FAIL)
        print_log("Use the sample file: twitch_colorchanger.conf.sample", bcolors.FAIL)
        sys.exit(1)
    
    # Validate users
    valid_users = validate_all_users(users)
    
    if not valid_users:
        logger.error("No valid user configurations found!")
        sys.exit(1)
    
    logger.info(f"✅ Found {len(valid_users)} valid user configuration(s)")
    return valid_users


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
