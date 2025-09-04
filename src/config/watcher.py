"""
Configuration file watcher for runtime config changes
"""

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer as _Observer

from ..constants import RELOAD_WATCH_DELAY
from ..logs.logger import logger
from .core import (
    _validate_and_filter_users,  # reuse core validation helper
    load_users_from_config,
    normalize_user_channels,
)


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for config file changes"""

    def __init__(self, config_file: str, watcher_instance: "ConfigWatcher"):
        super().__init__()
        self.config_file = os.path.abspath(config_file)
        self.watcher = watcher_instance
        self.last_modified = 0

    # Removed on_modified handler (unused).  # noqa: ERA001


class ConfigWatcher:
    """Watches config file for changes and triggers bot restart"""

    observer: Any | None
    running: bool
    paused: bool
    _pause_lock: threading.Lock

    def __init__(
        self, config_file: str, restart_callback: Callable[[list[dict[str, Any]]], Any]
    ):
        self.config_file = config_file
        self.restart_callback = restart_callback
        # Initialize runtime attributes
        self.observer = None
        self.running = False
        self.paused = False
        self._pause_lock = threading.Lock()

    def pause_watching(self) -> None:
        """Temporarily pause watching (for bot-initiated changes)"""
        with self._pause_lock:
            self.paused = True
            logger.log_event("config_watch", "paused", level=logging.DEBUG)

    def resume_watching(self) -> None:
        """Resume watching after bot-initiated changes (non-blocking)."""

        def _unpause():  # runs in thread after delay
            with self._pause_lock:
                self.paused = False
                logger.log_event("config_watch", "resumed", level=logging.DEBUG)

        # Use a timer thread instead of blocking sleep
        import threading
        import time as _time

        def _delay_then_unpause():
            _time.sleep(RELOAD_WATCH_DELAY)
            _unpause()

        threading.Thread(target=_delay_then_unpause, daemon=True).start()

    def start(self) -> None:
        """Start watching the config file"""
        if self.running:
            return

        config_dir = os.path.dirname(os.path.abspath(self.config_file))
        if not os.path.exists(config_dir):
            logger.log_event(
                "config_watch",
                "dir_missing",
                level=logging.WARNING,
                path=config_dir,
            )
            return

        try:
            observer = _Observer()
            event_handler = ConfigFileHandler(self.config_file, self)
            observer.schedule(event_handler, config_dir, recursive=False)
            observer.start()
            self.observer = observer
            self.running = True
            logger.log_event("config_watch", "start", path=self.config_file)
        except Exception as e:
            # Ensure we don't retain a partially started observer
            self.observer = None
            logger.log_event(
                "config_watch",
                "start_failed",
                level=logging.ERROR,
                error=str(e),
            )

    def stop(self) -> None:
        """Stop watching the config file"""
        obs = self.observer
        if self.running and obs is not None:
            try:
                obs.stop()
                obs.join()
            finally:
                self.running = False
                self.observer = None
                logger.log_event("config_watch", "stopped")

    def _on_config_changed(self) -> None:
        """Handle config file changes"""
        try:
            # Load and validate new config
            new_users_config = load_users_from_config(self.config_file)

            if not new_users_config:
                logger.log_event(
                    "config_watch",
                    "empty_or_invalid",
                    level=logging.WARNING,
                )
                return

            # Normalize channels for all users
            new_users_config, _ = normalize_user_channels(
                new_users_config, self.config_file
            )

            # Validate new configuration via shared helper
            valid_users = _validate_and_filter_users(new_users_config)

            if not valid_users:
                logger.log_event(
                    "config_watch",
                    "no_valid_users",
                    level=logging.ERROR,
                )
                return

            logger.log_event(
                "config_watch",
                "validation_passed",
                user_count=len(valid_users),
            )

            # Trigger bot restart with new config
            self.restart_callback(valid_users)

        except Exception as e:
            logger.log_event(
                "config_watch",
                "processing_error",
                level=logging.ERROR,
                error=str(e),
            )


async def create_config_watcher(
    config_file: str, restart_callback: Callable[[list[dict[str, Any]]], Any]
) -> ConfigWatcher:
    """Create and start a config file watcher"""
    watcher = ConfigWatcher(config_file, restart_callback)

    # Start watcher in executor to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, watcher.start)

    return watcher


## Removed legacy start_config_watcher (async factory create_config_watcher used)  # noqa: ERA001
