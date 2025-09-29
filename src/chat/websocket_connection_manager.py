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
import time
from typing import Any

import aiohttp

from ..errors.eventsub import EventSubConnectionError
from ..utils.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    get_circuit_breaker,
)
from .connection_state_manager import ConnectionState, ConnectionStateManager
from .message_transceiver import MessageTransceiver
from .protocols import WebSocketConnectionManagerProtocol
from .reconnection_manager import ReconnectionManager
from .websocket_connector import WebSocketConnector

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"

WEBSOCKET_NOT_CONNECTED_ERROR = "WebSocket not connected"


class WebSocketConnectionManager(WebSocketConnectionManagerProtocol):
    """Manages WebSocket connections for Twitch EventSub.

    This class orchestrates WebSocket connection management through composition
    of specialized components for connection, reconnection, messaging, and state tracking.

    Attributes:
        session (aiohttp.ClientSession): HTTP session for WebSocket connections.
        token (str): OAuth access token for authentication.
        client_id (str): Twitch client ID for authentication.
        connector (WebSocketConnector): Handles basic connection establishment and cleanup.
        reconnection_manager (ReconnectionManager): Manages reconnection with backoff.
        transceiver (MessageTransceiver): Handles sending and receiving messages.
        state_manager (ConnectionStateManager): Tracks connection state and health.
        _stop_event (asyncio.Event): Event to signal shutdown.
        _reconnect_requested (bool): Flag for reconnect request.
        _connection_count (int): Count of connection attempts for leak prevention.
        _last_cleanup_time (float): Timestamp of last cleanup.
        _cleanup_interval (float): Interval for periodic cleanup.
        _max_connection_attempts (int): Maximum allowed connection attempts.
        circuit_breaker: Circuit breaker for connection protection.
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

        # Compose specialized components
        self.connector = WebSocketConnector(session, token, client_id, ws_url)
        self._stop_event = asyncio.Event()
        self.reconnection_manager = ReconnectionManager(self.connector, self._stop_event)
        self.state_manager = ConnectionStateManager(self.connector)
        self.transceiver = MessageTransceiver(self.connector, self.state_manager.last_activity)

        self._reconnect_requested = False

        # Resource leak prevention and pooling
        self._connection_count = 0
        self._last_cleanup_time = time.monotonic()
        self._cleanup_interval = 300.0  # 5 minutes
        self._max_connection_attempts = 10
        self._connection_pool: set[WebSocketConnectionManager] = set()
        self._max_pool_size = 3  # Limit concurrent connections

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
        return self.state_manager.is_connected

    @property
    def session_id(self) -> str | None:
        """Get the current session ID.

        Returns:
            str | None: The session ID if connected, None otherwise.
        """
        return self.state_manager.session_id

    def is_healthy(self) -> bool:
        """Check if WebSocket connection is healthy and responsive.

        Returns:
            bool: True if connection is healthy, False otherwise.
        """
        return self.state_manager.is_healthy()

    async def connect(self) -> None:
        """Establish WebSocket connection and perform handshake.

        Connects to the WebSocket URL, handles authentication headers,
        performs handshake, and extracts session ID.

        Raises:
            EventSubConnectionError: If connection or handshake fails.
            CircuitBreakerOpenException: If circuit breaker is open.
        """
        # Check for too many connection attempts
        if self._is_too_many_attempts():
            logging.error("🚨 Too many connection attempts, backing off")
            raise EventSubConnectionError(
                "Too many connection attempts", operation_type="connect"
            )

        # Check connection pool limits
        if len(self._connection_pool) >= self._max_pool_size:
            logging.warning(f"🚨 Connection pool full ({len(self._connection_pool)}/{self._max_pool_size}), cleaning up stale connections")
            await self._cleanup_stale_connections()

        async def _perform_connection() -> None:
            """Internal connection logic wrapped by circuit breaker."""
            self.state_manager.connection_state = ConnectionState.CONNECTING
            self._connection_count += 1

            try:
                # Establish connection
                await self.connector.connect()
                logging.info(f"🔌 WebSocket connected to {self.connector.ws_url}")

                # Handle challenge if needed
                if self.state_manager.pending_challenge:
                    await self.reconnection_manager.handle_challenge(self.state_manager.pending_challenge)

                # Process welcome message
                await self._process_welcome()

                self.state_manager.connection_state = ConnectionState.CONNECTED
                logging.info(
                    f"✅ WebSocket handshake complete, session_id: {self.state_manager.session_id}"
                )

            except Exception as e:
                self.state_manager.connection_state = ConnectionState.DISCONNECTED
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
        self.state_manager.update_url(new_url)

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources.

        Closes the WebSocket connection gracefully and clears state.
        """
        self._stop_event.set()
        self.state_manager.connection_state = ConnectionState.DISCONNECTED
        await self.connector.disconnect()
        self._connection_count = 0

    def _should_cleanup(self) -> bool:
        """Check if periodic cleanup should run."""
        current_time = time.monotonic()
        return current_time - self._last_cleanup_time > self._cleanup_interval

    def _is_too_many_attempts(self) -> bool:
        """Check if connection attempts exceed threshold."""
        return self._connection_count > self._max_connection_attempts

    async def _perform_periodic_cleanup(self) -> None:
        """Perform periodic resource cleanup."""
        if not self._should_cleanup():
            return

        self._last_cleanup_time = time.monotonic()

        # Force cleanup if connection is stale
        if self.connector.ws and not self.connector.ws.closed:
            current_time = time.monotonic()
            if current_time - self.state_manager.last_activity[0] > 300.0:  # 5 minutes
                logging.info("🧹 Cleaning up stale WebSocket connection")
                await self.connector.cleanup_connection()
                self.state_manager.last_activity[0] = time.monotonic()

        # Clean up connection pool
        await self._cleanup_stale_connections()

    async def _cleanup_stale_connections(self) -> None:
        """Clean up stale connections from the pool."""
        current_time = time.monotonic()
        stale_connections = []

        # Find connections that haven't been active recently
        stale_connections = [
            conn for conn in self._connection_pool.copy()
            if (hasattr(conn, 'state_manager') and conn.state_manager and
                current_time - conn.state_manager.last_activity[0] > 600.0)  # 10 minutes
        ]

        # Remove and cleanup stale connections
        for conn in stale_connections:
            try:
                logging.info("🧹 Removing stale connection from pool")
                self._connection_pool.discard(conn)
                if conn.is_connected:
                    await conn.disconnect()
            except Exception as e:
                logging.warning(f"Failed to cleanup stale connection: {e}")

        # Log pool status
        if len(self._connection_pool) > 0:
            logging.debug(f"📊 Connection pool size: {len(self._connection_pool)}")

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send JSON data over WebSocket.

        Args:
            data (dict[str, Any]): Data to send as JSON.

        Raises:
            EventSubConnectionError: If not connected or send fails.
        """
        await self.transceiver.send_json(data)

    async def receive_message(self) -> aiohttp.WSMessage:
        """Receive a WebSocket message.

        Returns:
            aiohttp.WSMessage: Received message.

        Raises:
            EventSubConnectionError: If not connected or receive fails.
        """
        return await self.transceiver.receive_message()

    async def reconnect(self) -> bool:
        """Request reconnection with backoff.

        Sets the reconnect flag and handles reconnection logic.

        Returns:
            bool: True if reconnected successfully, False if abandoned.
        """
        self._reconnect_requested = True
        self.state_manager.connection_state = ConnectionState.RECONNECTING
        success = await self.reconnection_manager.reconnect()
        if success:
            await self._process_welcome()
            self.state_manager.connection_state = ConnectionState.CONNECTED
        return success

    async def _process_welcome(self) -> None:
        """Process welcome message and extract session ID.

        Raises:
            EventSubConnectionError: If welcome processing fails.
        """
        if not self.connector.ws:
            raise EventSubConnectionError(
                "No WebSocket connection", operation_type="welcome"
            )

        try:
            # If challenge was handled, welcome might already be received
            # For simplicity, always wait for welcome
            msg = await self.transceiver.receive_message()

            if msg.type != aiohttp.WSMsgType.TEXT:
                raise EventSubConnectionError(
                    "Invalid welcome message type", operation_type="welcome"
                )

            data = json.loads(msg.data)
            self.state_manager.session_id = data.get("payload", {}).get("session", {}).get("id")

            if not self.state_manager.session_id:
                raise EventSubConnectionError(
                    "No session ID in welcome", operation_type="welcome"
                )

        except Exception as e:
            if isinstance(e, EventSubConnectionError):
                raise
            raise EventSubConnectionError(
                f"Welcome processing failed: {str(e)}", operation_type="welcome"
            ) from e
