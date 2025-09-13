#!/usr/bin/env python3
"""
Main entry point for the Twitch Color Changer Bot
"""

import asyncio
import atexit
import logging
import os
import sys

# Import all modules first (required by E402)
from .bot.manager import run_bots
from .config import (
    get_configuration,
    normalize_user_channels,
    print_config_summary,
    setup_missing_tokens,
)
from .errors.handling import log_error

# Configure logging after imports to prevent other modules from configuring it
from .logging_config import LoggerConfigurator
from .utils import emit_startup_instructions

configurator = LoggerConfigurator()
configurator.configure()


async def main() -> None:
    """Main entry point for the Twitch Color Changer Bot application.

    This function initializes the application by loading configuration,
    setting up tokens, and starting the bot managers. It handles
    various exceptions and ensures proper shutdown.

    Raises:
        SystemExit: If a critical error occurs during initialization.
    """
    try:
        print("🚀 Starting Twitch Color Changer Bot")
        emit_startup_instructions()
        config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
        loaded_config = get_configuration()
        loaded_config, _ = normalize_user_channels(loaded_config, config_file)
        users_config = await setup_missing_tokens(loaded_config, config_file)
        print_config_summary(users_config)
        users_config_dicts = [u.to_dict() for u in users_config]
        await run_bots(users_config_dicts, config_file)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log_error("Main application error", e)
        sys.exit(1)
    finally:
        logging.info("✅ Application shutdown complete")


# Best-effort safety net: ensure any lingering aiohttp session is closed
@atexit.register
def _cleanup_any_context() -> None:  # pragma: no cover - process exit path
    """Cleanup function registered with atexit for emergency resource cleanup.

    This function is called when the process exits and attempts to clean up
    any remaining resources, particularly aiohttp sessions from the application
    context. It performs lazy imports to avoid side effects if not needed.
    """
    # Import lazily to avoid import side-effects if not needed
    from .application_context import (  # noqa: F401
        ApplicationContext,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except asyncio.CancelledError:
        sys.exit(0)
    except Exception as e:
        log_error("Top-level error", e)
        sys.exit(1)
