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
from .device_flow import DeviceCodeFlow

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
        print_log(f"  User {i}: {user['username']} -> is_prime_or_turbo: {user.get('is_prime_or_turbo', 'MISSING_FIELD')}", bcolors.OKCYAN, debug_only=True)


def _log_debug_data(save_data):
    """Log debug information about the data being saved (redacted)."""
    from .utils import redact_sensitive
    import json
    print_log("🔍 DEBUG: Exact JSON being written (redacted):", bcolors.HEADER, debug_only=True)
    print_log(json.dumps(redact_sensitive(save_data), indent=2), bcolors.OKCYAN, debug_only=True)

def _verify_saved_data(config_file):
    """Verify that the data was saved correctly"""
    try:
        with open(config_file, 'r') as f:
            verification_data = json.load(f)
        print_log(f"✅ VERIFICATION: File actually contains {len(verification_data.get('users', []))} users", bcolors.OKGREEN, debug_only=True)
        for i, user in enumerate(verification_data.get('users', []), 1):
            username = user.get('username', 'NO_USERNAME')
            is_prime_or_turbo = user.get('is_prime_or_turbo', 'MISSING_FIELD')
            print_log(f"  Verified User {i}: {username} -> is_prime_or_turbo: {is_prime_or_turbo}", bcolors.OKGREEN, debug_only=True)
    except Exception as verify_error:
        print_log(f"❌ VERIFICATION FAILED: {verify_error}", bcolors.FAIL, debug_only=True)


def save_users_to_config(users, config_file):
    """Save users to config file"""
    try:
        # Pause watcher during bot-initiated changes
        try:
            from .watcher_globals import pause_config_watcher, resume_config_watcher
            pause_config_watcher()
        except ImportError:
            pass  # Watcher not available
        
        # Ensure all users have is_prime_or_turbo field before saving
        for user in users:
            if 'is_prime_or_turbo' not in user:
                user['is_prime_or_turbo'] = True  # Default value
                print_log(f"🔧 Added missing is_prime_or_turbo field for {user.get('username', 'Unknown')}: {user['is_prime_or_turbo']}", bcolors.OKBLUE, debug_only=True)
        
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
        
        # Add small delay before resuming watcher to avoid detecting our own change
        import time
        time.sleep(0.5)
        
    except Exception as e:
        print_log(f"⚠️ Failed to save configuration: {e}", bcolors.FAIL)
        raise
    finally:
        # Always resume watcher
        try:
            from .watcher_globals import resume_config_watcher
            resume_config_watcher()
        except ImportError:
            pass


def update_user_in_config(user_config, config_file):
    """Update a specific user's configuration in the config file"""
    try:
        users = load_users_from_config(config_file)
        updated = False
        
        # Ensure the user_config has is_prime_or_turbo field
        if 'is_prime_or_turbo' not in user_config:
            user_config['is_prime_or_turbo'] = True  # Default value
            print_log(f"🔧 Added missing is_prime_or_turbo field for {user_config.get('username', 'Unknown')}: {user_config['is_prime_or_turbo']}", bcolors.OKBLUE, debug_only=True)
        
        # Find and update existing user
        for i, user in enumerate(users):
            if user.get('username') == user_config['username']:
                # Create a new config with proper field order
                merged_config = {
                    'username': user_config.get('username', user.get('username')),
                    'client_id': user_config.get('client_id', user.get('client_id')),
                    'client_secret': user_config.get('client_secret', user.get('client_secret')),
                    'access_token': user_config.get('access_token', user.get('access_token')),
                    'refresh_token': user_config.get('refresh_token', user.get('refresh_token')),
                    'channels': user_config.get('channels', user.get('channels', [])),
                    'is_prime_or_turbo': user_config.get('is_prime_or_turbo', user.get('is_prime_or_turbo', True))
                }
                # Remove any None values to keep config clean
                merged_config = {k: v for k, v in merged_config.items() if v is not None}
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
                user['is_prime_or_turbo'] = False
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
        print_log(f"   Is Prime or Turbo: {'Yes' if user.get('is_prime_or_turbo', True) else 'No'}")
        print_log(f"   Has Refresh Token: {'Yes' if user.get('refresh_token') else 'No'}")


async def setup_missing_tokens(users, config_file):
    """
    Automatically setup tokens for users that don't have them or can't renew them.
    Returns updated users list with new tokens.
    """
    updated_users = []
    needs_config_save = False
    
    for user in users:
        user_result = await _setup_user_tokens(user)
        updated_users.append(user_result['user'])
        if user_result['tokens_updated']:
            needs_config_save = True
    
    # Save config if any tokens were updated
    if needs_config_save:
        _save_updated_config(updated_users, config_file)
    
    return updated_users


async def _setup_user_tokens(user):
    """Setup tokens for a single user. Returns dict with user and update status."""
    username = user.get('username', 'Unknown')
    client_id = user.get('client_id', '')
    client_secret = user.get('client_secret', '')
    
    # Check if user has basic credentials
    if not client_id or not client_secret:
        print_log(f"❌ User {username} missing client_id or client_secret - skipping automatic setup", bcolors.FAIL)
        return {'user': user, 'tokens_updated': False}
    
    # Check if tokens exist and are valid/renewable
    tokens_result = await _validate_or_refresh_tokens(user)
    if tokens_result['valid']:
        return {'user': tokens_result['user'], 'tokens_updated': tokens_result['updated']}
    
    # Need new tokens via device flow
    return await _get_new_tokens_via_device_flow(user, client_id, client_secret)


async def _validate_or_refresh_tokens(user):
    """
    Validate existing tokens or refresh them using the bot's existing token management.
    This leverages the proven token handling in bot.py to avoid code duplication.
    """
    username = user.get('username', 'Unknown')
    access_token = user.get('access_token', '')
    refresh_token = user.get('refresh_token', '')
    client_id = user.get('client_id', '')
    client_secret = user.get('client_secret', '')
    
    if not access_token:
        print_log(f"🔑 {username}: No access token found", bcolors.WARNING, debug_only=True)
        return {'valid': False, 'user': user, 'updated': False}
    
    try:
        # Create a temporary bot instance to leverage existing token management
        from .bot import TwitchColorBot
        
        temp_bot = TwitchColorBot(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            nick=username,
            channels=["temp"],  # Temporary channel for validation
            is_prime_or_turbo=user.get('is_prime_or_turbo', True),
            config_file=None  # Don't auto-save during validation
        )
        
        # Use bot's proactive token checking with more aggressive refresh threshold
        # This checks if token expires in <24 hours (instead of <1 hour) for proactive refresh
        original_hours_method = temp_bot._hours_until_expiry
        def proactive_hours_check():
            hours = original_hours_method()
            return hours if hours < 24 else 0.5  # Trigger refresh if <24 hours remaining
        temp_bot._hours_until_expiry = proactive_hours_check
        
        # Use the bot's proven token validation and refresh logic
        token_valid = await temp_bot._check_and_refresh_token(force=False)
        
        if token_valid:
            # Check if tokens were updated during the process
            if (temp_bot.access_token != access_token or 
                temp_bot.refresh_token != refresh_token):
                # Update user config with refreshed tokens
                user['access_token'] = temp_bot.access_token
                user['refresh_token'] = temp_bot.refresh_token
                print_log(f"✅ {username}: Tokens proactively refreshed", bcolors.OKGREEN, debug_only=True)
                return {'valid': True, 'user': user, 'updated': True}
            else:
                print_log(f"✅ {username}: Tokens are valid", bcolors.OKGREEN, debug_only=True)
                return {'valid': True, 'user': user, 'updated': False}
        else:
            print_log(f"⚠️ {username}: Token validation/refresh failed", bcolors.WARNING, debug_only=True)
            return {'valid': False, 'user': user, 'updated': False}
        
    except Exception as e:
        print_log(f"⚠️ Token validation failed for {username}: {e}", bcolors.WARNING, debug_only=True)
        return {'valid': False, 'user': user, 'updated': False}


async def _get_new_tokens_via_device_flow(user, client_id, client_secret):
    """Get new tokens using device flow and ensure they're saved to config."""
    username = user.get('username', 'Unknown')
    print_log(f"\n🔑 User {username} needs new tokens", bcolors.WARNING)
    
    device_flow = DeviceCodeFlow(client_id, client_secret)
    try:
        token_result = await device_flow.get_user_tokens(username)
        if token_result:
            new_access_token, new_refresh_token = token_result
            user['access_token'] = new_access_token
            user['refresh_token'] = new_refresh_token
            
            # Immediately validate the new tokens to ensure they work
            # and get expiry information for proactive refresh
            validation_result = await _validate_new_tokens(user)
            if validation_result['valid']:
                print_log(f"✅ Successfully obtained and validated new tokens for {username}", bcolors.OKGREEN)
                return {'user': validation_result['user'], 'tokens_updated': True}
            else:
                print_log(f"⚠️ New tokens for {username} failed validation", bcolors.WARNING)
                return {'user': user, 'tokens_updated': True}  # Still save them, might work later
        else:
            print_log(f"❌ Failed to obtain tokens for {username}", bcolors.FAIL)
            return {'user': user, 'tokens_updated': False}
    except Exception as e:
        print_log(f"❌ Error during token setup for {username}: {e}", bcolors.FAIL)
        return {'user': user, 'tokens_updated': False}


async def _validate_new_tokens(user):
    """Validate newly obtained tokens and get expiry information."""
    username = user.get('username', 'Unknown')
    
    try:
        # Create a temporary bot instance to validate and get token expiry
        from .bot import TwitchColorBot
        
        temp_bot = TwitchColorBot(
            token=user['access_token'],
            refresh_token=user['refresh_token'],
            client_id=user['client_id'],
            client_secret=user['client_secret'],
            nick=username,
            channels=["temp"],  # Temporary channel for validation
            is_prime_or_turbo=user.get('is_prime_or_turbo', True),
            config_file=None  # Don't auto-save during validation
        )
        
        # Validate the new tokens
        valid = await temp_bot._validate_token_via_api()
        
        if valid:
            # Update user with any token information the bot might have gathered
            user['access_token'] = temp_bot.access_token
            user['refresh_token'] = temp_bot.refresh_token
            print_log(f"✅ New tokens for {username} validated successfully", bcolors.OKGREEN, debug_only=True)
            return {'valid': True, 'user': user}
        else:
            print_log(f"⚠️ New tokens for {username} validation failed", bcolors.WARNING, debug_only=True)
            return {'valid': False, 'user': user}
            
    except Exception as e:
        print_log(f"⚠️ Error validating new tokens for {username}: {e}", bcolors.WARNING, debug_only=True)
        return {'valid': False, 'user': user}


def _save_updated_config(updated_users, config_file):
    """Save updated configuration to file."""
    try:
        save_users_to_config(updated_users, config_file)
        print_log("💾 Configuration updated with new tokens", bcolors.OKGREEN)
    except Exception as e:
        print_log(f"❌ Failed to save updated configuration: {e}", bcolors.FAIL)
