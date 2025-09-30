"""Connection State Manager for tracking connection state and health."""

from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .websocket_connector import WebSocketConnector


class ConnectionState(Enum):
    """Enumeration of WebSocket connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class ConnectionStateManager:
    """Tracks connection state, activity monitoring, and health checks.

    Attributes:
        connector (WebSocketConnector): The WebSocket connector instance.
        connection_state (ConnectionState): Current connection state.
        session_id (str | None): Current EventSub session ID.
        pending_reconnect_session_id (str | None): Session ID for reconnect.
        pending_challenge (str | None): Pending challenge for handshake.
        last_sequence (int | None): Last received message sequence number.
        last_activity (list[float]): Timestamp of last WebSocket activity.
    """

    def __init__(self, connector: WebSocketConnector) -> None:
        """Initialize the Connection State Manager.

        Args:
            connector (WebSocketConnector): WebSocket connector.
        """
        self.connector = connector
        self.connection_state = ConnectionState.DISCONNECTED
        self.session_id: str | None = None
        self.pending_reconnect_session_id: str | None = None
        self.pending_challenge: str | None = None
        self.last_sequence: int | None = None
        self.last_activity = [time.monotonic()]

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected and active.

        Returns:
            bool: True if connected, False otherwise.
        """
        return self.connector.ws is not None and not (hasattr(self.connector.ws, 'closed') and self.connector.ws.closed)

    def is_healthy(self) -> bool:
        """Check if WebSocket connection is healthy and responsive.

        Returns:
            bool: True if connection is healthy, False otherwise.
        """
        if not self.is_connected:
            return False

        # Check if connection state indicates health
        if self.connection_state != ConnectionState.CONNECTED:
            return False

        # Check if session_id exists (indicates successful handshake)
        if not self.session_id:
            return False

        # Check if we've received activity recently (within last 60 seconds)
        # This helps detect stale connections
        current_time = time.monotonic()
        time_since_activity = current_time - self.last_activity[0]

        # If no activity for more than 60 seconds, consider it unhealthy
        if time_since_activity > 60.0:
            return False

        return True

    def update_url(self, new_url: str) -> None:
        """Update the WebSocket URL for reconnection.

        Args:
            new_url (str): The new WebSocket URL to use.
        """
        if new_url and new_url != self.connector.url:
            # Note: logging would be done in the main class
            self.connector.url = new_url
