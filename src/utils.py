"""
Utility functions for logging, user input, and common operations
"""

import os
from .colors import bcolors

# Global debug flag
DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')


def print_log(message, color="", debug_only=False):
    """Print log with ANSI colors. If debug_only=True, only print when DEBUG=True"""
    if debug_only and not DEBUG:
        return
        
    use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    if use_colors:
        print(f"{color}{message}{bcolors.ENDC}")
    else:
        print(message)


def print_instructions():
    """Display essential setup instructions"""
    print_log("="*60, bcolors.PURPLE)
    print_log("🎨 TWITCH COLORCHANGER BOT - Multi-User Support", bcolors.PURPLE)
    print_log("="*60, bcolors.PURPLE)
    
    print_log("\n🔧 Setup Instructions:")
    print_log("1. Create a Twitch application at: https://dev.twitch.tv/console/apps")
    print_log("2. Set OAuth Redirect URL to: https://twitchtokengenerator.com")
    print_log("3. Get your tokens at: https://twitchtokengenerator.com")
    print_log("   - Enter your Client ID and Client Secret")
    print_log("   - Select scopes: chat:read, user:manage:chat_color")
    print_log("   - Save the Access Token and Refresh Token")
    
    print_log("\n📁 Configuration:")
    print_log("• Copy twitch_colorchanger.conf.sample to twitch_colorchanger.conf")
    print_log("• Edit the config file with your credentials")
    print_log("• The bot will load all users from the config file")
    
    print_log("\n🎯 How it works:")
    print_log("• The bot monitors your chat messages")
    print_log("• After each message you send, it changes your username color")
    print_log("• Supports both preset Twitch colors and random hex colors")
    print_log("• Can run multiple users simultaneously")
    
    print_log("\n⚠️ IMPORTANT: Save Access Token, Refresh Token, Client ID, AND Client Secret")
