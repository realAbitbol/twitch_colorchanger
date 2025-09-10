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

from .bot.manager import run_bots
from .config import (
    get_configuration,
    normalize_user_channels,
    print_config_summary,
    setup_missing_tokens,
)
from .errors.handling import log_error
from .health import read_status
from .logs.logger import logger
from .utils import emit_startup_instructions


async def main() -> None:
    """Main function"""
    try:
        logger.log_event("app", "start")
        emit_startup_instructions()
        config_file = os.environ.get("TWITCH_CONF_FILE", "twitch_colorchanger.conf")
        loaded_config = get_configuration()
        loaded_config, _ = normalize_user_channels(loaded_config, config_file)
        users_config = await setup_missing_tokens(loaded_config, config_file)
        print_config_summary(users_config)
        await run_bots(users_config, config_file)
    except asyncio.CancelledError:
        logger.log_event(
            "app", "cancelled", level=logging.WARNING, human="Cancelled (Ctrl+C)"
        )
        raise
    except KeyboardInterrupt:
        logger.log_event("app", "interrupted", level=logging.WARNING)
    except Exception as e:  # noqa: BLE001
        log_error("Main application error", e)
        logger.log_event(
            "app",
            "critical_error",
            level=logging.CRITICAL,
            error=str(e),
            exc_info=True,
        )
        sys.exit(1)
    finally:
        logger.log_event("app", "shutdown_complete")


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
        logger.log_event(
            "app", "atexit_context_check_error", level=logging.DEBUG, error=str(e)
        )


if __name__ == "__main__":
    # Simple health check mode
    if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
        logger.log_event("app", "health_mode")
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
                logger.log_event(
                    "app",
                    "health_fail",
                    level=logging.ERROR,
                    error=f"consecutive_reconnect_failures={failures}",
                )
                sys.exit(1)

            now = time.time()
            if last_maintenance and (now - float(last_maintenance) > stale_threshold):
                logger.log_event(
                    "app",
                    "health_fail",
                    level=logging.ERROR,
                    error=f"last_maintenance_stale={now - float(last_maintenance):.0f}s",
                )
                sys.exit(1)

            # If we have an explicit last_ok timestamp too old, treat as failure
            if last_ok and (now - float(last_ok) > stale_threshold):
                logger.log_event(
                    "app",
                    "health_fail",
                    level=logging.ERROR,
                    error=f"last_reconnect_ok_stale={now - float(last_ok):.0f}s",
                )
                sys.exit(1)

            logger.log_event("app", "health_pass", user_count=len(health_config))
            sys.exit(0)
        except Exception as e:  # noqa: BLE001
            logger.log_event("app", "health_fail", level=logging.ERROR, error=str(e))
            sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - signal handling
        logger.log_event("app", "terminated_by_user")
        sys.exit(0)
    except asyncio.CancelledError:
        logger.log_event("app", "terminated_by_cancellation")
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        log_error("Top-level error", e)
        logger.log_event(
            "app",
            "top_level_error",
            level=logging.CRITICAL,
            error=str(e),
            exc_info=True,
        )
        sys.exit(1)
