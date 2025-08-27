"""
Utility functions for logging, user input, and common operations
"""

import os
from .colors import bcolors


def print_log(message, color=""):
    """Print log with ANSI colors if FORCE_COLOR is not false, else plain text"""
    use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    if use_colors:
        print(f"{color}{message}{bcolors.ENDC}")
    else:
        print(message)


def process_channels(channels_str):
    """Process comma-separated channel string into list of lowercase channel names"""
    return [ch.strip().lower() for ch in channels_str.split(',') if ch.strip()]


def print_instructions():
    """Display instructions for using the bot"""
    print_log("\n" + "="*80, bcolors.PURPLE)
    print_log("🎨 TWITCH COLORCHANGER BOT - Multi-User Support", bcolors.PURPLE)
    print_log("="*80, bcolors.PURPLE)
    
    print_log("\n🔧 Setup Instructions:")
    print_log("1. Create a Twitch application at: https://dev.twitch.tv/console/apps")
    print_log("2. Set OAuth Redirect URL to: http://localhost:3000")
    print_log("3. Get your tokens at: https://twitchapps.com/tmi/")
    print_log("   - Copy the Access Token (oauth:xxxxx)")
    print_log("   - Copy the Refresh Token")
    print_log("   - Copy your Client ID and Client Secret")
    
    print_log("\n⚠️ Token Requirements:")
    print_log("• Access Token: For API authentication")
    print_log("• Refresh Token: For automatic token renewal")
    print_log("• Client ID: Your Twitch application ID")
    print_log("• Client Secret: Your Twitch application secret")
    
    print_log("\n🎯 How it works:")
    print_log("• The bot monitors your chat messages")
    print_log("• After each message you send, it changes your username color")
    print_log("• Supports both preset Twitch colors and random hex colors")
    print_log("• Can run multiple users simultaneously")
    
    print_log("\n⚠️ IMPORTANT: Save ALL FOUR values - Access Token, Refresh Token, Client ID, AND Client Secret")
    
    print_log("\n🐳 Docker Multi-User Support:")
    print_log("Use numbered environment variables for each user:")
    print_log("   TWITCH_USERNAME_1, TWITCH_ACCESS_TOKEN_1, etc.")
    print_log("   TWITCH_USERNAME_2, TWITCH_ACCESS_TOKEN_2, etc.")


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
