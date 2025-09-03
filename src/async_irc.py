"""
Async IRC client for Twitch - Pure async implementation
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from .constants import (
    ASYNC_IRC_CONNECT_TIMEOUT,
    CHANNEL_JOIN_TIMEOUT,
    CONNECTION_RETRY_TIMEOUT,
    MAX_JOIN_ATTEMPTS,
    PING_EXPECTED_INTERVAL,
    SERVER_ACTIVITY_TIMEOUT,
)
from .irc_connection import ConnectionState, IRCConnectionController
from .irc_dispatcher import IRCDispatcher
from .irc_health import IRCHealthMonitor
from .irc_heartbeat import IRCHeartbeat
from .irc_join import IRCJoinManager
from .irc_listener import IRCListener
from .logger import logger

"""ConnectionState moved to irc_connection module"""


class AsyncTwitchIRC:  # pylint: disable=too-many-instance-attributes
    """Async IRC client for Twitch using asyncio - non-blocking operations"""

    def __init__(self):  # noqa: C901 - initialization grouped for clarity
        # --- Identity & channels ---
        self.username: str | None = None
        self.token: str | None = None
        self.channels: list[str] = []

        # --- Connection primitives ---
        self.server = "irc.chat.twitch.tv"
        self.port = 6667
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.running = False
        self.connected = False
        self.state = ConnectionState.DISCONNECTED

        # --- Synchronization ---
        self._reconnect_lock = asyncio.Lock()

        # --- Join tracking ---
        self.joined_channels: set[str] = set()
        self.confirmed_channels: set[str] = set()
        self.pending_joins: dict[str, dict[str, float | int]] = {}
        self.join_timeout = CHANNEL_JOIN_TIMEOUT
        self.max_join_attempts = MAX_JOIN_ATTEMPTS

        # --- Health timestamps ---
        self.last_server_activity = 0.0
        self.server_activity_timeout = SERVER_ACTIVITY_TIMEOUT
        self.last_ping_from_server = 0.0
        self.expected_ping_interval = PING_EXPECTED_INTERVAL

        # --- Reconnection counters ---
        self.consecutive_failures = 0
        self.last_reconnect_attempt = 0.0
        self.connection_start_time = 0.0

        # --- Handlers ---
        self.message_handler: Callable[[str, str, str], Any] | None = None
        self.color_change_handler: Callable[[str, str, str], Any] | None = None

        # --- Buffers / misc ---
        self.message_buffer = ""
        self._join_grace_deadline: float | None = None

        # --- Controllers ---
        self.connection_controller = IRCConnectionController(self)
        self.health_monitor = IRCHealthMonitor(self)

        # --- Extracted managers ---
        self.dispatcher = IRCDispatcher(self)
        self.heartbeat = IRCHeartbeat(self)
        self.join_manager = IRCJoinManager(self)
        self.listener = IRCListener(self)

    def _set_state(self, new_state: ConnectionState):
        """Set connection state with structured logging"""
        if self.state != new_state:
            old_state = (
                self.state.name if hasattr(self.state, "name") else str(self.state)
            )
            logger.log_event(
                "irc",
                "state_change",
                level=logging.DEBUG,
                user=self.username,
                old_state=old_state,
                new_state=new_state.name,
            )
            self.state = new_state

    async def connect(self, token: str, username: str, channel: str) -> bool:
        """Connect to Twitch IRC with the given credentials"""
        # Set connection details
        self.username = username.lower()
        self.token = token if token.startswith("oauth:") else f"oauth:{token}"
        self.channels = [channel.lower()]

        try:
            self._set_state(ConnectionState.CONNECTING)
            logger.log_event(
                "irc",
                "connect_start",
                user=self.username,
                server=self.server,
                port=self.port,
            )
            logger.log_event(
                "irc",
                "open_connection",
                level=logging.DEBUG,
                user=self.username,
                timeout=ASYNC_IRC_CONNECT_TIMEOUT,
            )
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.server, self.port),
                timeout=ASYNC_IRC_CONNECT_TIMEOUT,
            )
            logger.log_event(
                "irc",
                "connection_established",
                level=logging.DEBUG,
                user=self.username,
            )

            # Send authentication
            self._set_state(ConnectionState.AUTHENTICATING)
            await self._send_line(f"PASS {self.token}")
            await self._send_line(f"NICK {self.username}")

            # Enable required capabilities for Twitch
            await self._send_line("CAP REQ :twitch.tv/membership")
            await self._send_line("CAP REQ :twitch.tv/tags")
            await self._send_line("CAP REQ :twitch.tv/commands")

            logger.log_event(
                "irc",
                "auth_sent",
                level=logging.DEBUG,
                user=self.username,
                wait_seconds=2,
            )
            # Wait for connection confirmation
            await asyncio.sleep(2)  # Give server time to process

            logger.log_event(
                "irc",
                "join_begin",
                level=logging.DEBUG,
                user=self.username,
                channel=channel.lower(),
            )
            # Start temporary message processing for join confirmation
            self._set_state(ConnectionState.JOINING)
            success = await self.join_manager.join_with_message_processing(channel)
            if success:
                self.connected = True
                self._reset_connection_timer()  # Reset timer after successful connection
                self._set_state(ConnectionState.READY)
                self._join_grace_deadline = time.time() + 30  # 30s grace for joins
                logger.log_event(
                    "irc",
                    "connect_success",
                    user=self.username,
                    channel=channel.lower(),
                )
                return True

            logger.log_event(
                "irc",
                "connect_join_failed",
                level=logging.ERROR,
                user=self.username,
                channel=channel.lower(),
            )
            await self.disconnect()
            return False

        except TimeoutError:
            logger.log_event(
                "irc",
                "connect_timeout",
                level=logging.ERROR,
                user=self.username,
                timeout=ASYNC_IRC_CONNECT_TIMEOUT,
            )
            await self.disconnect()
            return False
        except OSError as e:
            if "Connection reset by peer" in str(e):
                logger.log_event(
                    "irc",
                    "connect_reset",
                    level=logging.ERROR,
                    user=self.username,
                    error=str(e),
                )
            else:
                logger.log_event(
                    "irc",
                    "connect_network_error",
                    level=logging.ERROR,
                    user=self.username,
                    error=str(e),
                )
            await self.disconnect()
            return False
        except Exception as e:
            logger.log_event(
                "irc",
                "connect_network_error",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            await self.disconnect()
            return False

    # Join workflow moved to IRCJoinManager

    async def _send_line(self, message: str):
        """Send a line to the IRC server"""
        if self.writer:
            line = f"{message}\r\n"
            self.writer.write(line.encode("utf-8"))
            await self.writer.drain()

    async def join_channel(self, channel: str) -> bool:  # public API retained
        return await self.join_manager.join_channel(channel)

    async def listen(self):  # public API retained
        return await self.listener.listen()

    # Dispatcher & message handling moved to IRCDispatcher

    # Heartbeat logic moved to IRCHeartbeat

    def update_token(self, new_token: str):
        """Update the stored token for future reconnections"""
        self.token = (
            new_token if new_token.startswith("oauth:") else f"oauth:{new_token}"
        )
        logger.log_event(
            "irc", "token_updated", level=logging.DEBUG, user=self.username
        )

    async def disconnect(self):
        """Disconnect from IRC server"""
        self.running = False
        self.connected = False

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logger.log_event(
                    "irc",
                    "connect_network_error",
                    level=logging.ERROR,
                    user=self.username,
                    error=str(e),
                )
            finally:
                self.writer = None
                self.reader = None

        # Reset state
        self.joined_channels.clear()
        self.confirmed_channels.clear()
        self.pending_joins.clear()
        self.message_buffer = ""
        self._set_state(ConnectionState.DISCONNECTED)
        logger.log_event(
            "irc", "disconnected", level=logging.WARNING, user=self.username
        )

    async def force_reconnect(self) -> bool:  # wrapper to keep public API
        return await self.connection_controller.force_reconnect()

    # Backoff moved to IRCConnectionController

    def set_message_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the message handler callback (can be sync or async)"""
        self.message_handler = handler

    def set_color_change_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the color change handler callback (can be sync or async)"""
        self.color_change_handler = handler

    def get_connection_stats(self) -> dict:
        return self.health_monitor.get_connection_stats()

    def is_healthy(self) -> bool:
        return self.health_monitor.is_healthy()

    # Health logic moved to IRCHealthMonitor

    # Health logic moved to IRCHealthMonitor

    # Health logic moved to IRCHealthMonitor

    # Health logic moved to IRCHealthMonitor

    def get_health_snapshot(self) -> dict[str, Any]:
        return self.health_monitor.get_health_snapshot()

    def _should_retry_connection(self) -> bool:
        """Check if we should continue retrying connection attempts"""
        if self.connection_start_time == 0:
            self.connection_start_time = time.time()
            return True

        elapsed = time.time() - self.connection_start_time
        if elapsed > CONNECTION_RETRY_TIMEOUT:
            logger.log_event(
                "irc",
                "connection_retry_timeout",
                level=logging.WARNING,
                user=self.username,
                timeout=CONNECTION_RETRY_TIMEOUT,
            )
            return False
        return True

    def _reset_connection_timer(self):
        """Reset the connection retry timer after successful connection"""
        self.connection_start_time = 0
        self.consecutive_failures = 0
