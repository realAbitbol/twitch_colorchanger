from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .eventsub_backend import EventSubChatBackend


class ReconnectionCoordinator:
    """Coordinates reconnection logic including session reconnect handling, resubscription, and connection health validation."""

    def __init__(self, backend: EventSubChatBackend) -> None:
        self.backend = backend

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
        """Handle reconnection logic with connection health validation.

        Returns:
            bool: True if reconnection successful and healthy, False otherwise.
        """
        if not self.backend._ws_manager:
            return False

        old_session_id = getattr(self.backend._ws_manager, "session_id", None)
        logging.debug(f"Reconnect: old WS session_id={old_session_id}")

        try:
            success = await self.backend._ws_manager.reconnect()
        except Exception as e:
            logging.error(f"Reconnect failed: {e}")
            return False

        if not success:
            return False

        # Validate connection health after reconnection
        if not await self.validate_connection_health():
            logging.error("Connection health validation failed after reconnection")
            return False

        # Reset last activity timestamp after successful reconnection
        self.backend._ws_manager.state_manager.last_activity[0] = time.monotonic()

        new_session_id = getattr(self.backend._ws_manager, "session_id", None)
        logging.debug(f"Reconnect successful: new WS session_id={new_session_id}")

        if self.backend._sub_manager and new_session_id:
            try:
                await self.backend._sub_manager.update_session_id(new_session_id)
            except Exception as e:
                logging.error(f"Failed to update session_id: {e}")
                return False

        if self.backend._sub_manager:
            try:
                await self.backend._sub_manager.unsubscribe_all()
            except Exception as e:
                logging.error(f"Failed to unsubscribe all: {e}")
                return False

        if self.backend._subscription_coordinator is None:
            raise AssertionError("SubscriptionCoordinator not initialized")
        try:
            resub_success = await self.backend._subscription_coordinator.resubscribe_all_channels()
        except Exception as e:
            logging.error(f"Failed to resubscribe all channels: {e}")
            return False

        if not resub_success:
            return False

        return True

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
