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


def process_channels(channels_str):
    """Process comma-separated channel string into list of lowercase channel names"""
    return [ch.strip().lower() for ch in channels_str.split(',') if ch.strip()]


def print_instructions():
    """Display essential setup instructions"""
    print_log("="*80, bcolors.PURPLE)
    print_log("🎨 TWITCH COLORCHANGER BOT - Multi-User Support", bcolors.PURPLE)
    print_log("="*80, bcolors.PURPLE)
    
    print_log("\n🔧 Setup Instructions:")
    print_log("1. Create a Twitch application at: https://dev.twitch.tv/console/apps")
    print_log("2. Set OAuth Redirect URL to: https://twitchtokengenerator.com")
    print_log("3. Get your tokens at: https://twitchtokengenerator.com")
    print_log("   - Enter your Client ID and Client Secret")
    print_log("   - Select scopes: chat:read, user:manage:chat_color")
    print_log("   - Save the Access Token and Refresh Token")
    
    print_log("\n🎯 How it works:")
    print_log("• The bot monitors your chat messages")
    print_log("• After each message you send, it changes your username color")
    print_log("• Supports both preset Twitch colors and random hex colors")
    print_log("• Can run multiple users simultaneously")
    
    print_log("\n⚠️ IMPORTANT: Save Access Token, Refresh Token, Client ID, AND Client Secret")
    
    print_log("\n🐳 Docker Multi-User Support:")
    print_log("Use numbered environment variables: TWITCH_USERNAME_1, TWITCH_ACCESS_TOKEN_1, etc.")


def prompt_for_user():
    """Prompt user for their Twitch credentials and settings"""
    print_log("\n" + "="*50, bcolors.OKCYAN)
    print_log("👤 Enter user details:", bcolors.OKCYAN)
    print_log("="*50, bcolors.OKCYAN)
    
    username = input("👤 Username: ").strip()
    access_token = input("🎫 Access Token: ").strip()
    refresh_token = input("🔄 Refresh Token: ").strip()
    client_id = input("📱 Client ID: ").strip()
    client_secret = input("🔒 Client Secret: ").strip()
    channels_input = input("📺 Channels (comma-separated): ").strip()
    channels = process_channels(channels_input)
    use_random_colors_input = input("🎲 Use random hex colors? [Y/n]: ").strip().lower()
    use_random_colors = use_random_colors_input != 'n'
    
    return {
        'username': username,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
        'channels': channels,
        'use_random_colors': use_random_colors
    }
