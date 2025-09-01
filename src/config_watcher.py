"""
Configuration file watcher for runtime config changes
"""

import asyncio
import os
import threading
import time
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import load_users_from_config, normalize_user_channels
from .config_validator import get_valid_users
from .logger import logger


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for config file changes"""

    def __init__(self, config_file: str, watcher_instance):
        super().__init__()
        self.config_file = os.path.abspath(config_file)
        self.watcher = watcher_instance
        self.last_modified = 0

    def on_modified(self, event):
        """Handle file modification events"""
        if event.is_directory:
            return

        # Check if it's our config file
        if os.path.abspath(event.src_path) == self.config_file:
            # Check if watcher is paused (bot-initiated change)
            with self.watcher._pause_lock:
                if self.watcher.paused:
                    logger.debug("📝 Config change ignored (bot-initiated)")
                    return

            # Debounce rapid fire events (some editors trigger multiple events)
            current_time = time.time()
            if current_time - self.last_modified < 1.0:  # 1 second debounce
                return
            self.last_modified = current_time

            logger.info(f"📁 Config file changed: {event.src_path}")

            # Run callback in a thread to avoid blocking the file watcher
            threading.Thread(
                target=self.watcher._on_config_changed, daemon=True
            ).start()


class ConfigWatcher:
    """Watches config file for changes and triggers bot restart"""

    def __init__(self, config_file: str, restart_callback: Callable):
        self.config_file = config_file
        self.restart_callback = restart_callback
        self.observer = None
        self.running = False
        self.paused = False
        self._pause_lock = threading.Lock()

    def pause_watching(self):
        """Temporarily pause watching (for bot-initiated changes)"""
        with self._pause_lock:
            self.paused = True
            logger.debug("⏸️ Config watcher paused (bot update in progress)")

    def resume_watching(self):
        """Resume watching after bot-initiated changes"""
        with self._pause_lock:
            self.paused = False
            logger.debug("▶️ Config watcher resumed")

    def start(self):
        """Start watching the config file"""
        if self.running:
            return

        config_dir = os.path.dirname(os.path.abspath(self.config_file))
        if not os.path.exists(config_dir):
            logger.warning(f"Config directory does not exist: {config_dir}")
            return

        self.observer = Observer()
        event_handler = ConfigFileHandler(self.config_file, self)

        try:
            self.observer.schedule(event_handler, config_dir, recursive=False)
            self.observer.start()
            self.running = True
            logger.info(f"👀 Started watching config file: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to start config watcher: {e}")

    def stop(self):
        """Stop watching the config file"""
        if self.observer and self.running:
            self.observer.stop()
            self.observer.join()
            self.running = False
            logger.info("👁️ Stopped config file watcher")

    def _on_config_changed(self):
        """Handle config file changes"""
        try:
            # Load and validate new config
            new_users_config = load_users_from_config(self.config_file)

            if not new_users_config:
                logger.warning("⚠️ Config file is empty or invalid, ignoring changes")
                return

            # Normalize channels for all users
            new_users_config, _ = normalize_user_channels(new_users_config, self.config_file)

            # Validate new configuration
            valid_users = get_valid_users(new_users_config)

            if not valid_users:
                logger.error("❌ New config contains no valid users, ignoring changes")
                return

            logger.info(
                f"✅ Config validation passed - {len(valid_users)} valid user(s)"
            )

            # Trigger bot restart with new config
            self.restart_callback(valid_users)

        except Exception as e:
            logger.error(f"Error processing config change: {e}")


async def create_config_watcher(
    config_file: str, restart_callback: Callable
) -> ConfigWatcher:
    """Create and start a config file watcher"""
    watcher = ConfigWatcher(config_file, restart_callback)

    # Start watcher in executor to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, watcher.start)

    return watcher


def start_config_watcher(config_file: str, restart_callback: Callable) -> ConfigWatcher:
    """Create and start a config file watcher (synchronous version for testing)"""
    watcher = ConfigWatcher(config_file, restart_callback)
    watcher.start()
    return watcher
