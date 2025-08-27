#!/usr/bin/env python3
"""
Main entry point for the Twitch Color Changer Bot
"""

import asyncio
import sys
import os

from src.config import get_configuration, print_config_summary
from src.bot_manager import run_bots
from src.utils import print_instructions, print_log
from src.colors import bcolors


async def main():
    """Main function"""
    try:
        # Print welcome message and instructions
        print_instructions()
        
        # Get configuration (Docker or interactive mode)
        users_config = get_configuration()
        
        # Print configuration summary
        print_config_summary(users_config)
        
        # Get config file path for token saving
        config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
        
        # Run all bots
        await run_bots(users_config, config_file)
        
    except KeyboardInterrupt:
        print_log("\n⌨️ Interrupted by user", bcolors.WARNING)
    except Exception as e:
        print_log(f"\n❌ Fatal error: {e}", bcolors.FAIL)
        sys.exit(1)


if __name__ == "__main__":
    # Simple health check mode
    if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
        print_log("🏥 Health check mode", bcolors.OKBLUE)
        try:
            users_config = get_configuration()
            print_log(f"✅ Health check passed - {len(users_config)} user(s) configured", bcolors.OKGREEN)
            sys.exit(0)
        except Exception as e:
            print_log(f"❌ Health check failed: {e}", bcolors.FAIL)
            sys.exit(1)
    
    asyncio.run(main())
