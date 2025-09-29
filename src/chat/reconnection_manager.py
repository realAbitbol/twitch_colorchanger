"""Reconnection Manager for handling reconnection attempts with backoff."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import TYPE_CHECKING

import aiohttp

from ..constants import (
    EVENTSUB_MAX_BACKOFF_SECONDS,
    WEBSOCKET_MESSAGE_TIMEOUT_SECONDS,
)
from ..errors.eventsub import EventSubConnectionError
from ..utils.circuit_breaker import get_circuit_breaker

if TYPE_CHECKING:
    from .websocket_connector import WebSocketConnector


class ReconnectionManager:
    """Manages reconnection attempts with exponential backoff and circuit breaker integration.

    Attributes:
        connector (WebSocketConnector): The WebSocket connector instance.
        backoff (float): Current reconnect backoff time.
        max_backoff (float): Maximum backoff time.
        _stop_event (asyncio.Event): Event to signal shutdown.
        circuit_breaker: Circuit breaker for connections.
    """

    def __init__(self, connector: WebSocketConnector, stop_event: asyncio.Event) -> None:
        """Initialize the Reconnection Manager.

        Args:
            connector (WebSocketConnector): WebSocket connector.
            stop_event (asyncio.Event): Stop event for cancellation.
        """
        self.connector = connector
        self.backoff = 1.0
        self.max_backoff = EVENTSUB_MAX_BACKOFF_SECONDS
        self._stop_event = stop_event
        self.circuit_breaker = get_circuit_breaker("websocket_connection")

    async def reconnect(self) -> bool:
        """Attempt a single reconnection.

        Returns:
            bool: True if reconnected successfully, False otherwise.
        """
        return await self._reconnect_once()

    async def _reconnect_once(self) -> bool:
        """Attempt a single reconnection.

        Returns:
            bool: True if reconnected successfully, False otherwise.
        """
        try:
            # Check if circuit breaker is open before attempting connection
            if self.circuit_breaker.is_open:
                logging.info("⏸️ Circuit breaker open, cannot reconnect")
                return False

            # Cleanup previous connection
            await self.connector.disconnect()

            logging.info(f"🔄 Reconnect attempt to {self.connector.ws_url}")

            # Attempt connection
            await self.connector.connect()

            logging.info("✅ Reconnect successful")
            return True

        except Exception as e:
            logging.error(f"❌ Reconnect failed: {str(e)}")
            return False

    async def handle_challenge(self, pending_challenge: str | None) -> None:
        """Handle challenge/response handshake.

        Args:
            pending_challenge (str | None): The pending challenge.

        Raises:
            EventSubConnectionError: If challenge handling fails.
        """
        if not self.connector.ws or not pending_challenge:
            return

        logging.info(f"🔐 Handling challenge: {pending_challenge}")

        try:
            # Wait for challenge message
            msg = await asyncio.wait_for(
                self.connector.ws.receive(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
            )

            if msg.type != aiohttp.WSMsgType.TEXT:
                raise EventSubConnectionError(
                    "Invalid challenge message type", operation_type="challenge"
                )

            data = json.loads(msg.data)
            received_challenge = data.get("challenge")

            if received_challenge != pending_challenge:
                raise EventSubConnectionError(
                    "Challenge mismatch", operation_type="challenge"
                )

            # Send response
            response = {"type": "challenge_response", "challenge": received_challenge}
            await self.connector.ws.send_json(response)

            logging.info("✅ Challenge response sent")

        except Exception as e:
            if isinstance(e, EventSubConnectionError):
                raise
            raise EventSubConnectionError(
                f"Challenge handling failed: {str(e)}", operation_type="challenge"
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
