"""WebSocket Connector for basic connection establishment and cleanup."""

from __future__ import annotations

import logging
import time

import aiohttp

from ..constants import WEBSOCKET_HEARTBEAT_SECONDS
from ..errors.eventsub import EventSubConnectionError

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"


class WebSocketConnector:
    """Handles basic WebSocket connection establishment and cleanup.

    Attributes:
        session (aiohttp.ClientSession): HTTP session for WebSocket connections.
        token (str): OAuth access token for authentication.
        client_id (str): Twitch client ID for authentication.
        ws_url (str): Current WebSocket URL.
        ws (aiohttp.ClientWebSocketResponse | None): Active WebSocket connection.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        client_id: str,
        ws_url: str = EVENTSUB_WS_URL,
    ) -> None:
        """Initialize the WebSocket Connector.

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


    async def connect(self) -> None:
        """Establish WebSocket connection.

        Connects to the WebSocket URL with authentication headers.

        Raises:
            EventSubConnectionError: If connection fails.
        """
        try:
            # Clean up any existing connection first
            await self._cleanup_connection()

            headers = {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self.token}",
            }
            logging.info(f"🔌 WebSocket connecting to {self.ws_url} at {time.time():.2f}, sending headers with Bearer token (length: {len(self.token)})")
            self.ws = await self.session.ws_connect(
                self.ws_url,
                heartbeat=WEBSOCKET_HEARTBEAT_SECONDS,
                headers=headers,
                protocols=("twitch-eventsub-ws",),
            )
            logging.info(f"🔌 WebSocket connected to {self.ws_url}")

        except Exception as e:
            raise EventSubConnectionError(
                f"WebSocket connection failed: {str(e)}", operation_type="connect"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources.

        Closes the WebSocket connection gracefully.
        """
        await self._cleanup_connection()

    async def cleanup_connection(self) -> None:
        """Public method to cleanup the connection."""
        await self._cleanup_connection()

    async def _cleanup_connection(self) -> None:
        """Clean up the current WebSocket connection and resources."""
        if self.ws:
            if self.ws.closed:
                logging.info(f"🔌 WebSocket already closed by server: code={self.ws.close_code}, reason={self.ws.close_reason}")
            else:
                try:
                    await self.ws.close(code=1000)
                    logging.info("🔌 WebSocket disconnected")
                except Exception as e:
                    logging.warning(f"⚠️ WebSocket close error: {str(e)}")
        self.ws = None
