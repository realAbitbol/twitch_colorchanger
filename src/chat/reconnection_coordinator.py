from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .eventsub_backend import EventSubChatBackend

from ..errors.internal import BotRestartException


class ReconnectionCoordinator:
    """Coordinates reconnection logic including session reconnect handling, resubscription, and connection health validation."""

    def __init__(self, backend: EventSubChatBackend) -> None:
        self.backend = backend
        self.backoff = 5.0  # Initial backoff: 5 seconds
        self.max_backoff = 60.0  # Maximum backoff: 60 seconds
        self.max_attempts = 3  # Maximum reconnection attempts
        self.consecutive_failures = 0  # Track consecutive reconnection failures

    async def handle_session_reconnect(self, data: dict[str, Any]) -> None:
        """Handle session reconnect message from Twitch.

        Updates the WebSocket URL and initiates reconnection.

        Args:
            data: The session_reconnect message data.
        """
        try:
            reconnect_url = (
                data.get("payload", {}).get("session", {}).get("reconnect_url")
            )
            if not reconnect_url:
                logging.error("Session reconnect message missing reconnect_url")
                return

            if self.backend._ws_manager:
                self.backend._ws_manager.update_url(reconnect_url)
                logging.info(
                    f"Updated WebSocket URL to {reconnect_url}, initiating reconnect"
                )
                await self.handle_reconnect()
            else:
                logging.error("No WebSocket manager available for session reconnect")
        except Exception as e:
            logging.error(f"Failed to handle session reconnect: {str(e)}")

    async def handle_reconnect(self) -> bool:
        """Handle reconnection logic with exponential backoff and connection health validation.

        Returns:
            bool: True if reconnection successful and healthy, False otherwise.
        """
        if not self.backend._ws_manager:
            return False

        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            start_time = time.time()
            logging.info(f"🔄 Starting WebSocket reconnection attempt {attempt} at {start_time:.2f}")

            old_session_id = getattr(self.backend._ws_manager, "session_id", None)
            logging.debug(f"Reconnect: old WS session_id={old_session_id}")

            try:
                success = await self.backend._ws_manager.reconnect()
            except Exception as e:
                duration = time.time() - start_time
                logging.error(f"🔄 Reconnection attempt {attempt} failed after {duration:.2f}s: {e}")

                if attempt < self.max_attempts:
                    # Apply backoff
                    sleep_time = self.backoff + self._jitter(0, 0.25 * self.backoff)
                    await asyncio.sleep(sleep_time)
                    self.backoff = min(self.backoff * 2, self.max_backoff)
                continue

            if not success:
                duration = time.time() - start_time
                logging.error(f"🔄 WebSocket reconnection attempt {attempt} failed after {duration:.2f}s")

                if attempt < self.max_attempts:
                    # Apply backoff
                    sleep_time = self.backoff + self._jitter(0, 0.25 * self.backoff)
                    await asyncio.sleep(sleep_time)
                    self.backoff = min(self.backoff * 2, self.max_backoff)
                continue

            # Validate connection health after reconnection
            if not await self.validate_connection_health():
                duration = time.time() - start_time
                logging.error(f"🔄 Connection health validation failed after reconnection attempt {attempt} ({duration:.2f}s)")

                if attempt < self.max_attempts:
                    # Apply backoff
                    sleep_time = self.backoff + self._jitter(0, 0.25 * self.backoff)
                    await asyncio.sleep(sleep_time)
                    self.backoff = min(self.backoff * 2, self.max_backoff)
                continue

            # Reset last activity timestamp after successful reconnection
            self.backend._ws_manager.state_manager.last_activity[0] = time.monotonic()

            # Reset backoff on success
            self.backoff = 5.0

            new_session_id = getattr(self.backend._ws_manager, "session_id", None)
            logging.debug(f"Reconnect successful: new WS session_id={new_session_id}")

            if self.backend._sub_manager and new_session_id:
                try:
                    await self.backend._sub_manager.update_session_id(new_session_id)
                except Exception as e:
                    duration = time.time() - start_time
                    logging.error(f"🔄 Failed to update session_id after {duration:.2f}s: {e}")
                    return False

            if self.backend._sub_manager:
                try:
                    await self.backend._sub_manager.unsubscribe_all()
                except Exception as e:
                    duration = time.time() - start_time
                    logging.error(f"🔄 Failed to unsubscribe all after {duration:.2f}s: {e}")
                    return False

            if self.backend._subscription_coordinator is None:
                raise AssertionError("SubscriptionCoordinator not initialized")
            try:
                resub_success = await self.backend._subscription_coordinator.resubscribe_all_channels()
            except Exception as e:
                duration = time.time() - start_time
                logging.error(f"🔄 Failed to resubscribe all channels after {duration:.2f}s: {e}")
                return False

            if not resub_success:
                duration = time.time() - start_time
                logging.error(f"🔄 Resubscription failed after {duration:.2f}s")
                return False

            duration = time.time() - start_time
            logging.info(f"🔄 WebSocket reconnection successful on attempt {attempt}, completed in {duration:.2f}s")
            self.consecutive_failures = 0  # Reset on success
            return True

        logging.error(f"🔄 Reconnection failed after {self.max_attempts} attempts")
        self.consecutive_failures += 1
        if self.consecutive_failures >= 6:
            logging.error("🔄 Multiple reconnection failures, restarting app")
            import sys
            sys.exit(1)
        elif self.consecutive_failures >= 3:
            logging.warning("🔄 Multiple reconnection failures, restarting bot")
            raise BotRestartException("Bot restart required due to persistent reconnection failures")
        return False

    def _jitter(self, a: float, b: float) -> float:
        """Generate jitter for backoff timing.

        Args:
            a (float): Minimum value.
            b (float): Maximum value.

        Returns:
            float: Random value between a and b.
        """
        if b <= a:
            return a
        span = b - a
        r = secrets.randbelow(1000) / 1000.0
        return a + r * span

    async def validate_connection_health(self) -> bool:
        """Validate that the WebSocket connection is healthy after reconnection.

        Returns:
            bool: True if connection is healthy, False otherwise.
        """
        if not self.backend._ws_manager:
            logging.error("No WebSocket manager for health validation")
            return False

        # Use the WebSocket manager's built-in health check
        if not self.backend._ws_manager.is_healthy():
            logging.error("WebSocket manager reports unhealthy connection")
            return False

        return True
