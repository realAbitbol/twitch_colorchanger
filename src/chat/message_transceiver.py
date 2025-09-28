"""Message Transceiver for sending and receiving WebSocket messages."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from ..constants import WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
from ..errors.eventsub import EventSubConnectionError

if TYPE_CHECKING:
    from .websocket_connector import WebSocketConnector


WEBSOCKET_NOT_CONNECTED_ERROR = "WebSocket not connected"


class MessageTransceiver:
    """Handles sending and receiving WebSocket messages with timeout management.

    Attributes:
        connector (WebSocketConnector): The WebSocket connector instance.
        last_activity (float): Timestamp of last activity.
    """

    def __init__(self, connector: WebSocketConnector, last_activity: float) -> None:
        """Initialize the Message Transceiver.

        Args:
            connector (WebSocketConnector): WebSocket connector.
            last_activity (float): Reference to last activity timestamp.
        """
        self.connector = connector
        self.last_activity = last_activity

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send JSON data over WebSocket.

        Args:
            data (dict[str, Any]): Data to send as JSON.

        Raises:
            EventSubConnectionError: If not connected or send fails.
        """
        if not self.connector.ws or self.connector.ws.closed:
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="send"
            )

        try:
            await self.connector.ws.send_json(data)
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
        if not self.connector.ws or self.connector.ws.closed:
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="receive"
            )

        try:
            msg = await asyncio.wait_for(
                self.connector.ws.receive(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
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
