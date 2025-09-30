"""WebSocket Connector for basic connection establishment and cleanup."""

from __future__ import annotations

import logging

import websockets

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"


class TwitchEventSubProtocol(websockets.WebSocketClientProtocol):
    """Custom WebSocket protocol for Twitch EventSub connections."""

    async def pong(self, data: bytes = b'') -> None:
        """Log when a pong is sent to Twitch."""
        logging.info(f"🏓 Pong sent to Twitch: {data.hex() if data else 'no data'}")
        await super().pong(data)


class WebSocketConnector:
    """Handles basic WebSocket connection establishment and cleanup.

    Attributes:
        session: HTTP session (kept for compatibility but not used for WebSocket).
        token (str): OAuth access token for authentication.
        client_id (str): Twitch client ID for authentication.
        ws_url (str): Current WebSocket URL.
        ws (websockets.WebSocketClientProtocol | None): Active WebSocket connection.
    """

    def __init__(
        self,
        token: str,
        client_id: str,
        ws_url: str = EVENTSUB_WS_URL,
    ) -> None:
        """Initialize the WebSocket Connector.

        Args:
            token (str): OAuth access token.
            client_id (str): Twitch client ID.
            ws_url (str): Initial WebSocket URL.
        """
        self.token = token
        self.client_id = client_id
        self.ws_url = ws_url
        self.ws: websockets.WebSocketClientProtocol | None = None

    def _get_headers(self):
        return {"Client-Id": self.client_id, "Authorization": f"Bearer {self.token}"}

    async def connect(self):
        logging.info(f"🔌 Connecting to WebSocket at {self.ws_url}")
        await self._cleanup_connection()
        try:
            self.ws = await websockets.connect(
                self.ws_url,
                extra_headers=self._get_headers(),
                subprotocols=("twitch-eventsub-ws",),
                ping_interval=None,
                create_protocol=TwitchEventSubProtocol
            )
            logging.info("🔌 WebSocket connected successfully")
            return self.ws
        except Exception as e:
            from ..errors.eventsub import EventSubConnectionError
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
            if hasattr(self.ws, 'closed') and self.ws.closed:
                code = getattr(self.ws, 'close_code', None)
                reason = getattr(self.ws, 'close_reason', None)
                if reason and isinstance(reason, bytes):
                    reason = reason.decode('utf-8')
                logging.info(f"🔌 WebSocket already closed: code={code}, reason={reason}")
            else:
                try:
                    await self.ws.close(code=1000)
                    code = getattr(self.ws, 'close_code', None)
                    reason = getattr(self.ws, 'close_reason', None)
                    if reason and isinstance(reason, bytes):
                        reason = reason.decode('utf-8')
                    logging.info(f"🔌 WebSocket disconnected: code={code}, reason={reason}")
                except Exception as e:
                    logging.warning(f"⚠️ WebSocket close error: {str(e)}")
                    if hasattr(self.ws, 'closed') and self.ws.closed:
                        code = getattr(self.ws, 'close_code', None)
                        reason = getattr(self.ws, 'close_reason', None)
                        if reason and isinstance(reason, bytes):
                            reason = reason.decode('utf-8')
                        logging.warning(f"⚠️ WebSocket closed with error: code={code}, reason={reason}")
        self.ws = None
