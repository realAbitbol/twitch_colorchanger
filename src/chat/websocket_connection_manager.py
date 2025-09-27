"""WebSocket Connection Manager for Twitch EventSub.

This module provides a WebSocketConnectionManager class that handles
WebSocket connection establishment, handshake, session management,
reconnection with backoff, connection state tracking, and challenge/response
handling for Twitch EventSub.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from enum import Enum
from typing import Any

import aiohttp

from ..constants import (
    EVENTSUB_JITTER_FACTOR,
    EVENTSUB_MAX_BACKOFF_SECONDS,
    EVENTSUB_RECONNECT_DELAY_SECONDS,
    WEBSOCKET_HEARTBEAT_SECONDS,
    WEBSOCKET_MESSAGE_TIMEOUT_SECONDS,
)
from ..errors.eventsub import EventSubConnectionError
from ..utils.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    get_circuit_breaker,
)
from .protocols import WebSocketConnectionManagerProtocol

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"

WEBSOCKET_NOT_CONNECTED_ERROR = "WebSocket not connected"


class ConnectionState(Enum):
    """Enumeration of WebSocket connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class WebSocketConnectionManager(WebSocketConnectionManagerProtocol):
    """Manages WebSocket connections for Twitch EventSub.

    This class handles the complete lifecycle of WebSocket connections including
    establishment, handshake, session management, reconnection with exponential
    backoff, connection state tracking, and challenge/response handling.

    Attributes:
        session (aiohttp.ClientSession): HTTP session for WebSocket connections.
        token (str): OAuth access token for authentication.
        client_id (str): Twitch client ID for authentication.
        ws_url (str): Current WebSocket URL (may change via reconnect).
        ws (aiohttp.ClientWebSocketResponse | None): Active WebSocket connection.
        session_id (str | None): Current EventSub session ID.
        pending_reconnect_session_id (str | None): Session ID for reconnect.
        pending_challenge (str | None): Pending challenge for handshake.
        connection_state (ConnectionState): Current connection state.
        last_sequence (int | None): Last received message sequence number.
        backoff (float): Current reconnect backoff time.
        max_backoff (float): Maximum backoff time.
        last_activity (float): Timestamp of last WebSocket activity.
        _stop_event (asyncio.Event): Event to signal shutdown.
        _reconnect_requested (bool): Flag for reconnect request.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        client_id: str,
        ws_url: str = EVENTSUB_WS_URL,
    ) -> None:
        """Initialize the WebSocket Connection Manager.

        Args:
            session (aiohttp.ClientSession): HTTP session for connections.
            token (str): OAuth access token.
            client_id (str): Twitch client ID.
            ws_url (str): Initial WebSocket URL.
        """
        self.session = session
        self.token = token
        self.client_id = client_id
        self.ws_url = ws_url
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.session_id: str | None = None
        self.pending_reconnect_session_id: str | None = None
        self.pending_challenge: str | None = None
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_sequence: int | None = None
        self.backoff = 1.0
        self.max_backoff = EVENTSUB_MAX_BACKOFF_SECONDS
        self.last_activity = time.monotonic()
        self._stop_event = asyncio.Event()
        self._reconnect_requested = False

        # Circuit breaker for WebSocket connections
        cb_config = CircuitBreakerConfig(
            name="websocket_connection",
            failure_threshold=3,
            recovery_timeout=30.0,
            success_threshold=2,
        )
        self.circuit_breaker = get_circuit_breaker("websocket_connection", cb_config)

    async def __aenter__(self) -> WebSocketConnectionManager:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected and active.

        Returns:
            bool: True if connected, False otherwise.
        """
        return self.ws is not None and not self.ws.closed

    async def connect(self) -> None:
        """Establish WebSocket connection and perform handshake.

        Connects to the WebSocket URL, handles authentication headers,
        performs handshake, and extracts session ID.

        Raises:
            EventSubConnectionError: If connection or handshake fails.
            CircuitBreakerOpenException: If circuit breaker is open.
        """
        async def _perform_connection() -> None:
            """Internal connection logic wrapped by circuit breaker."""
            self.connection_state = ConnectionState.CONNECTING
            try:
                headers = {
                    "Client-Id": self.client_id,
                    "Authorization": f"Bearer {self.token}",
                }
                self.ws = await self.session.ws_connect(
                    self.ws_url,
                    heartbeat=WEBSOCKET_HEARTBEAT_SECONDS,
                    headers=headers,
                    protocols=("twitch-eventsub-ws",),
                )
                logging.info(f"🔌 WebSocket connected to {self.ws_url}")

                # Handle challenge if needed
                if self.pending_challenge:
                    await self._handle_challenge()

                # Process welcome message
                await self._process_welcome()

                self.connection_state = ConnectionState.CONNECTED
                logging.info(
                    f"✅ WebSocket handshake complete, session_id: {self.session_id}"
                )

            except Exception as e:
                self.connection_state = ConnectionState.DISCONNECTED
                if isinstance(e, EventSubConnectionError):
                    raise
                raise EventSubConnectionError(
                    f"WebSocket connection failed: {str(e)}", operation_type="connect"
                ) from e

        try:
            await self.circuit_breaker.call(_perform_connection)
        except CircuitBreakerOpenException:
            logging.error("🚨 WebSocket connection blocked by circuit breaker")
            raise EventSubConnectionError(
                "WebSocket connection blocked by circuit breaker", operation_type="connect"
            ) from CircuitBreakerOpenException("Circuit breaker is open")

    def update_url(self, new_url: str) -> None:
        """Update the WebSocket URL for reconnection.

        Args:
            new_url (str): The new WebSocket URL to use.
        """
        if new_url and new_url != self.ws_url:
            logging.info(f"🔄 Updating WebSocket URL from {self.ws_url} to {new_url}")
            self.ws_url = new_url

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources.

        Closes the WebSocket connection gracefully and clears state.
        """
        self._stop_event.set()
        self.connection_state = ConnectionState.DISCONNECTED
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close(code=1000)
                logging.info("🔌 WebSocket disconnected")
            except Exception as e:
                logging.warning(f"⚠️ WebSocket close error: {str(e)}")
        self.ws = None
        self.session_id = None
        self.last_sequence = None

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send JSON data over WebSocket.

        Args:
            data (dict[str, Any]): Data to send as JSON.

        Raises:
            EventSubConnectionError: If not connected or send fails.
        """
        if not self.is_connected:
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="send"
            )

        try:
            if self.ws is None:
                raise EventSubConnectionError(
                    WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="send"
                )
            await self.ws.send_json(data)
            self.last_activity = time.monotonic()
        except Exception as e:
            raise EventSubConnectionError(
                f"WebSocket send failed: {str(e)}", operation_type="send"
            ) from e

    async def receive_message(self) -> aiohttp.WSMessage:
        """Receive a WebSocket message.

        Returns:
            aiohttp.WSMessage: Received message.

        Raises:
            EventSubConnectionError: If not connected or receive fails.
        """
        if not self.is_connected:
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="receive"
            )

        try:
            if self.ws is None:
                raise EventSubConnectionError(
                    WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="receive"
                )
            msg = await asyncio.wait_for(
                self.ws.receive(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
            )
            self.last_activity = time.monotonic()
            return msg
        except TimeoutError:
            raise EventSubConnectionError(
                "WebSocket receive timeout", operation_type="receive"
            ) from TimeoutError()
        except Exception as e:
            if isinstance(e, EventSubConnectionError):
                raise
            raise EventSubConnectionError(
                f"WebSocket receive failed: {str(e)}", operation_type="receive"
            ) from e

    async def reconnect(self) -> bool:
        """Request reconnection with backoff.

        Sets the reconnect flag and handles reconnection logic.

        Returns:
            bool: True if reconnected successfully, False if abandoned.
        """
        self._reconnect_requested = True
        self.connection_state = ConnectionState.RECONNECTING
        return await self._reconnect_with_backoff()

    async def _handle_challenge(self) -> None:
        """Handle challenge/response handshake.

        Waits for challenge message, verifies it, and sends response.

        Raises:
            EventSubConnectionError: If challenge handling fails.
        """
        if not self.ws or not self.pending_challenge:
            return

        logging.info(f"🔐 Handling challenge: {self.pending_challenge}")

        try:
            # Wait for challenge message
            msg = await asyncio.wait_for(
                self.ws.receive(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
            )

            if msg.type != aiohttp.WSMsgType.TEXT:
                raise EventSubConnectionError(
                    "Invalid challenge message type", operation_type="challenge"
                )

            data = json.loads(msg.data)
            received_challenge = data.get("challenge")

            if received_challenge != self.pending_challenge:
                raise EventSubConnectionError(
                    "Challenge mismatch", operation_type="challenge"
                )

            # Send response
            response = {"type": "challenge_response", "challenge": received_challenge}
            await self.ws.send_json(response)

            logging.info("✅ Challenge response sent")
            self.pending_challenge = None

        except Exception as e:
            if isinstance(e, EventSubConnectionError):
                raise
            raise EventSubConnectionError(
                f"Challenge handling failed: {str(e)}", operation_type="challenge"
            ) from e

    async def _process_welcome(self) -> None:
        """Process welcome message and extract session ID.

        Raises:
            EventSubConnectionError: If welcome processing fails.
        """
        if not self.ws:
            raise EventSubConnectionError(
                "No WebSocket connection", operation_type="welcome"
            )

        try:
            # If challenge was handled, welcome might already be received
            # For simplicity, always wait for welcome
            msg = await asyncio.wait_for(
                self.ws.receive(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
            )

            if msg.type != aiohttp.WSMsgType.TEXT:
                raise EventSubConnectionError(
                    "Invalid welcome message type", operation_type="welcome"
                )

            data = json.loads(msg.data)
            self.session_id = data.get("payload", {}).get("session", {}).get("id")

            if not self.session_id:
                raise EventSubConnectionError(
                    "No session ID in welcome", operation_type="welcome"
                )

        except Exception as e:
            if isinstance(e, EventSubConnectionError):
                raise
            raise EventSubConnectionError(
                f"Welcome processing failed: {str(e)}", operation_type="welcome"
            ) from e

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

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff.

        Attempts reconnection with increasing backoff times until successful
        or stop event is set. Respects circuit breaker state to avoid
        hammering failing endpoints.

        Returns:
            bool: True if reconnected successfully, False if abandoned.
        """
        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1

            # Check if circuit breaker is open before attempting connection
            if self.circuit_breaker.is_open:
                sleep_time = self.circuit_breaker.config.recovery_timeout
                logging.info(
                    f"⏸️ Circuit breaker open, waiting {sleep_time}s before retry"
                )
                await asyncio.sleep(sleep_time)
                continue

            try:
                # Cleanup previous connection
                await self.disconnect()

                # Wait before reconnect
                await asyncio.sleep(EVENTSUB_RECONNECT_DELAY_SECONDS)

                logging.info(f"🔄 Reconnect attempt {attempt} to {self.ws_url}")

                # Attempt connection (protected by circuit breaker)
                await self.connect()

                # Reset backoff on success
                self.backoff = 1.0
                self._reconnect_requested = False
                self.connection_state = ConnectionState.CONNECTED
                logging.info(f"✅ Reconnect successful on attempt {attempt}")
                return True

            except Exception as e:
                logging.error(f"❌ Reconnect failed attempt {attempt}: {str(e)}")

                # Apply backoff
                sleep_time = self.backoff + self._jitter(
                    0, EVENTSUB_JITTER_FACTOR * self.backoff
                )
                await asyncio.sleep(sleep_time)
                self.backoff = min(self.backoff * 2, self.max_backoff)

        logging.error("❌ Reconnect abandoned")
        return False
