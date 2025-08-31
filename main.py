#!/usr/bin/env python3
"""
Main entry point for the Twitch Color Changer Bot
"""

import asyncio
import sys
import os

from src.config import get_configuration, print_config_summary, setup_missing_tokens
from src.bot_manager import run_bots
from src.utils import print_instructions
from src.logger import logger
from src.error_handling import log_error


async def main():
    """Main function"""
    try:
        logger.info("🚀 Starting Twitch Color Changer Bot")

        # Print welcome message and instructions
        print_instructions()

        # Get config file path for token saving
        config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")

        # Get configuration from config file
        users_config = get_configuration()

        # Setup missing tokens automatically (device flow fallback)
        users_config = await setup_missing_tokens(users_config, config_file)

        # Print configuration summary
        print_config_summary(users_config)

        # Run all bots (signal handlers are set up in bot_manager)
        await run_bots(users_config, config_file)
    except KeyboardInterrupt:
        logger.warning("⌨️ Interrupted by user")
    except Exception as e:
        log_error("Main application error", e)
        logger.critical(f"Critical error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup resources
        logger.info("🏁 Application shutdown complete")


if __name__ == "__main__":
    # Simple health check mode
    if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
        logger.info("🏥 Health check mode")
        try:
            users_config = get_configuration()
            logger.info(
                f"✅ Health check passed - {len(users_config)} user(s) configured"
            )
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
        log_error("Top-level error", e)
        logger.critical(f"Critical error occurred: {e}", exc_info=True)
        sys.exit(1)
