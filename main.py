#!/usr/bin/env python3
"""
Main entry point for the Twitch Color Changer Bot
"""

import asyncio
import sys
import os
import signal

from src.config import get_configuration, print_config_summary
from src.bot_manager import run_bots
from src.utils import print_instructions
from src.logger import logger
from src.error_handling import setup_error_handlers, handle_critical_error
from src.http_client import close_http_client


async def main():
    """Main function"""
    try:
        # Setup error handling system
        setup_error_handlers()
        logger.info("🚀 Starting Twitch Color Changer Bot")
        
        # Print welcome message and instructions
        print_instructions()
        
        # Get configuration (Docker or interactive mode)
        users_config = get_configuration()
        
        # Print configuration summary
        print_config_summary(users_config)
        
        # Get config file path for token saving
        config_file = os.environ.get('TWITCH_CONF_FILE', "twitch_colorchanger.conf")
        
        # Setup signal handlers for graceful shutdown
        setup_signal_handlers()
        
        # Run all bots
        await run_bots(users_config, config_file)
        
    except KeyboardInterrupt:
        logger.warning("⌨️ Interrupted by user")
    except Exception as e:
        handle_critical_error(e, "Main application error")
    finally:
        # Cleanup resources
        await close_http_client()
        logger.info("🏁 Application shutdown complete")


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, _frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        # This will cause KeyboardInterrupt to be raised in the main loop
        raise KeyboardInterrupt()
    
    # Setup signal handlers for Unix systems
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    # Simple health check mode
    if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
        logger.info("🏥 Health check mode")
        try:
            users_config = get_configuration()
            logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
            sys.exit(0)
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle KeyboardInterrupt at the top level
        logger.info("Application terminated by user")
        sys.exit(0)
    except Exception as e:
        handle_critical_error(e, "Top-level error")
