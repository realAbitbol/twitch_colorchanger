"""Message Transceiver for sending and receiving WebSocket messages."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from ..constants import WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
from ..errors.eventsub import EventSubConnectionError

if TYPE_CHECKING:
    from .websocket_connector import WebSocketConnector


WEBSOCKET_NOT_CONNECTED_ERROR = "WebSocket not connected"


class WSMessage:
    """Simple WebSocket message class to mimic aiohttp.WSMessage."""
    def __init__(self, type_: str, data: Any):
        self.type = type_
        self.data = data


WSMsgType = type('WSMsgType', (), {'TEXT': 'text'})()


class MessageTransceiver:
    """Handles sending and receiving WebSocket messages with timeout management.

    Attributes:
        connector (WebSocketConnector): The WebSocket connector instance.
        last_activity (list[float]): Reference to last activity timestamp.
    """

    def __init__(self, connector: WebSocketConnector, last_activity: list[float]) -> None:
        """Initialize the Message Transceiver.

        Args:
            connector (WebSocketConnector): WebSocket connector.
            last_activity (list[float]): Reference to last activity timestamp.
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
        if not self.connector.ws or (hasattr(self.connector.ws, 'closed') and self.connector.ws.closed):
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="send"
            )

        try:
            await self.connector.ws.send(json.dumps(data))
            self.last_activity[0] = time.monotonic()
        except Exception as e:
            raise EventSubConnectionError(
                f"WebSocket send failed: {str(e)}", operation_type="send"
            ) from e

    async def receive_message(self) -> WSMessage:
        """Receive a WebSocket message.

        Returns:
            WSMessage: Received message.

        Raises:
            EventSubConnectionError: If not connected or receive fails.
        """
        if not self.connector.ws or (hasattr(self.connector.ws, 'closed') and self.connector.ws.closed):
            raise EventSubConnectionError(
                WEBSOCKET_NOT_CONNECTED_ERROR, operation_type="receive"
            )

        try:
            message = await asyncio.wait_for(
                self.connector.ws.recv(), timeout=WEBSOCKET_MESSAGE_TIMEOUT_SECONDS
            )
            self.last_activity[0] = time.monotonic()

            # For websockets library, message is just the data string
            # Handle mock objects that have .data attribute
            data = message.data if hasattr(message, 'data') else message

            # Determine message type based on data
            if isinstance(data, bytes) and data == b'ping':
                msg_type = "ping"
            else:
                msg_type = "text"

            msg = WSMessage(msg_type, data)
            return msg
        except StopAsyncIteration:
            raise EventSubConnectionError(
                "WebSocket closed", operation_type="receive"
            ) from None
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
