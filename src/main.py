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
from .utils import emit_startup_instructions

# Configure logging after imports to prevent other modules from configuring it
debug_env = os.environ.get("DEBUG", "").lower()
log_level = logging.DEBUG if debug_env in ("true", "1", "yes") else logging.INFO


# ANSI color codes for log levels
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colored log levels"""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        # Get the colored level name with fixed width alignment
        level_name = record.levelname
        colored_level = f"{self.COLORS.get(level_name, '')}{level_name:<8}{self.RESET}"

        # Format the message without logger name
        message = record.getMessage()

        # Return formatted string with level and message
        return f"{colored_level} {message}"


formatter = ColoredFormatter("%(message)s")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(formatter)

# Configure logging with no logger name in format
logging.basicConfig(
    level=log_level,
    handlers=[handler],
    format="%(message)s",  # Use our formatter's format
)
logging.getLogger().setLevel(log_level)

# Apply our formatter to all existing handlers
root_logger = logging.getLogger()
for h in root_logger.handlers:
    h.setFormatter(formatter)

# Disable watchdog logging after imports but before any logging calls
# Monkey-patch logging.getLogger to disable watchdog loggers
_original_getLogger = logging.getLogger


def patched_get_logger(name=None):
    logger = _original_getLogger(name)
    if name and (
        name.startswith("watchdog") or "fsevents" in name or name == "fsevents"
    ):
        logger.disabled = True
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        logger.handlers.clear()
        # Add a null handler to completely suppress output
        null_handler = logging.NullHandler()
        null_handler.setLevel(logging.CRITICAL)
        logger.addHandler(null_handler)
        # Also ensure parent loggers don't propagate
        logger.parent = None
    return logger


logging.getLogger = patched_get_logger

# Also disable the main watchdog logger
watchdog_logger = _original_getLogger("watchdog")
watchdog_logger.disabled = True
watchdog_logger.setLevel(logging.CRITICAL)
watchdog_logger.propagate = False
watchdog_logger.addHandler(logging.NullHandler())

# Also disable fsevents logger specifically
fsevents_logger = _original_getLogger("fsevents")
fsevents_logger.disabled = True
fsevents_logger.setLevel(logging.CRITICAL)
fsevents_logger.propagate = False
fsevents_logger.addHandler(logging.NullHandler())


async def main() -> None:
    """Main function"""
    try:
        print("🚀 Starting Twitch Color Changer Bot")
        emit_startup_instructions()
        config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
        loaded_config = get_configuration()
        loaded_config, _ = normalize_user_channels(loaded_config, config_file)
        users_config = await setup_missing_tokens(loaded_config, config_file)
        print_config_summary(users_config)
        await run_bots(users_config, config_file)
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
