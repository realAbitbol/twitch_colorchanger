"""
Utility functions for logging, user input, and common operations
"""

import os
from .colors import bcolors

# Global debug flag
DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')


SENSITIVE_KEYS = {"client_secret", "access_token", "refresh_token"}

def sanitize_for_log(data):
    """Redact sensitive fields from dict/list objects before logging."""
    if isinstance(data, dict):
        return {k: ("<REDACTED>" if k in SENSITIVE_KEYS else sanitize_for_log(v)) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_for_log(item) for item in data]
    # allow other base types to pass through unchanged
    return data

def print_log(message, color="", debug_only=False):
    """Print log with ANSI colors. If debug_only=True, only print when DEBUG=True"""
    if debug_only and not DEBUG:
        return
        
    # Sanitization: for dict/list messages, redact secrets
    if isinstance(message, (dict, list)):
        from pprint import pformat
        sanitized = sanitize_for_log(message)
        message_str = pformat(sanitized)
    else:
        message_str = str(message)

    use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    if use_colors:
        print(f"{color}{message_str}{bcolors.ENDC}")
    else:
        print(message_str)


def print_instructions():
    """Display essential setup instructions"""
    print_log("="*60, bcolors.PURPLE)
    print_log("🎨 TWITCH COLORCHANGER BOT - Multi-User Support", bcolors.PURPLE)
    print_log("="*60, bcolors.PURPLE)
    
    print_log("\n🔧 Setup Instructions:")
    print_log("1. Create a Twitch application at: https://dev.twitch.tv/console/apps")
    print_log("2. Set OAuth Redirect URL to: https://twitchtokengenerator.com")
    print_log("3. Copy your Client ID and Client Secret")
    
    print_log("\n📁 Configuration (Automatic Setup - Recommended):")
    print_log("• Copy twitch_colorchanger.conf.sample to twitch_colorchanger.conf")
    print_log("• Add your username, client_id, and client_secret")
    print_log("• Run the bot - it will automatically handle token authorization!")
    print_log("• Follow the displayed URL and enter the code when prompted")
    print_log("• Bot continues automatically once authorized")
    
    print_log("\n📁 Configuration (Manual Setup - Alternative):")
    print_log("• Generate tokens at: https://twitchtokengenerator.com")
    print_log("  - Enter your Client ID and Client Secret")
    print_log("  - Select scopes: chat:read, user:manage:chat_color")
    print_log("  - Save the Access Token and Refresh Token")
    print_log("• Add all credentials to the config file")
    
    print_log("\n🎯 How it works:")
    print_log("• The bot monitors your chat messages")
    print_log("• After each message you send, it changes your username color")
    print_log("• Supports both preset Twitch colors and random hex colors")
    print_log("• Can run multiple users simultaneously")
    print_log("• Automatically refreshes tokens to minimize re-authorization")
    
    print_log("\n⚠️ IMPORTANT: Keep your Client ID and Client Secret secure!")
