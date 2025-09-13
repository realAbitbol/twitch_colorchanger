#!/usr/bin/env python3
"""
Main entry point for the Twitch Color Changer Bot
"""

import asyncio
import atexit
import logging
import os
import sys
import time

# Import all modules first (required by E402)
from .bot.manager import run_bots
from .config import (
    get_configuration,
    normalize_user_channels,
    print_config_summary,
    setup_missing_tokens,
)
from .errors.handling import log_error
from .health import read_status
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
        logging.warning("Cancelled (Ctrl+C)")
        raise
    except KeyboardInterrupt:
        logging.warning("👋 Application terminated by user")
    except Exception as e:  # noqa: BLE001
        log_error("Main application error", e)
        logging.critical(f"💥 Critical error occurred: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        logging.info("✅ Application shutdown complete")


# Best-effort safety net: ensure any lingering aiohttp session is closed
@atexit.register
def _cleanup_any_context() -> None:  # pragma: no cover - process exit path
    try:  # best-effort; nothing to close explicitly yet
        # Import lazily to avoid import side-effects if not needed
        from .application_context import (  # noqa: F401
            ApplicationContext,
        )
    except Exception as e:  # noqa: BLE001
        # Log at debug to avoid noise
        logging.debug(f"⚠️ Atexit context check error: {str(e)}")


if __name__ == "__main__":
    # Simple health check mode
    if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
        print("🩺 Health check mode")
        try:
            # Basic config sanity check
            health_config = get_configuration()
            # Consult runtime health status file (written by background tasks)
            status = read_status()
            # Thresholds configurable via env
            max_failures = int(
                os.environ.get("TWITCH_HEALTH_MAX_RECONNECT_FAILURES", "5")
            )
            stale_threshold = int(os.environ.get("TWITCH_HEALTH_STALE_SECONDS", "600"))

            failures = int(status.get("consecutive_reconnect_failures", 0))
            last_maintenance = status.get("last_maintenance")
            last_ok = status.get("last_reconnect_ok")

            if failures >= max_failures:
                print(
                    f"❌ Health check failed: consecutive_reconnect_failures={failures}"
                )
                sys.exit(1)

            now = time.time()
            if last_maintenance and (now - float(last_maintenance) > stale_threshold):
                print(
                    f"❌ Health check failed: last_maintenance_stale={now - float(last_maintenance):.0f}s"
                )
                sys.exit(1)

            # If we have an explicit last_ok timestamp too old, treat as failure
            if last_ok and (now - float(last_ok) > stale_threshold):
                print(
                    f"❌ Health check failed: last_reconnect_ok_stale={now - float(last_ok):.0f}s"
                )
                sys.exit(1)

            print(f"✅ Health check passed users={len(health_config)}")
            sys.exit(0)
        except Exception as e:  # noqa: BLE001
            print(f"❌ Health check failed: {str(e)}")
            sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - signal handling
        logging.info("👋 Application terminated by user")
        sys.exit(0)
    except asyncio.CancelledError:
        logging.info("🛑 Application terminated by cancellation signal")
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        log_error("Top-level error", e)
        logging.critical(f"💥 Top-level critical error: {str(e)}", exc_info=True)
        sys.exit(1)
