"""
Async IRC client for Twitch - Pure async implementation
"""

import asyncio
import inspect
import logging
import secrets
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from .constants import (
    ASYNC_IRC_CONNECT_TIMEOUT,
    ASYNC_IRC_JOIN_TIMEOUT,
    ASYNC_IRC_READ_TIMEOUT,
    ASYNC_IRC_RECONNECT_TIMEOUT,
    BACKOFF_BASE_DELAY,
    BACKOFF_JITTER_FACTOR,
    BACKOFF_MAX_DELAY,
    BACKOFF_MULTIPLIER,
    CHANNEL_JOIN_TIMEOUT,
    CONNECTION_RETRY_TIMEOUT,
    MAX_JOIN_ATTEMPTS,
    PING_EXPECTED_INTERVAL,
    RECONNECT_DELAY,
    SERVER_ACTIVITY_TIMEOUT,
)
from .logger import logger


class ConnectionState(Enum):
    """IRC connection state for better state management"""

    DISCONNECTED = auto()
    CONNECTING = auto()
    AUTHENTICATING = auto()
    JOINING = auto()
    READY = auto()
    RECONNECTING = auto()
    DEGRADED = auto()


class AsyncTwitchIRC:  # pylint: disable=too-many-instance-attributes
    """Async IRC client for Twitch using asyncio - non-blocking operations"""

    def __init__(self):
        # IRC connection details (set during connect)
        self.username = None
        self.token = None
        self.channels = []

        # IRC connection
        self.server = "irc.chat.twitch.tv"
        self.port = 6667
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.running = False
        self.connected = False
        self.state = ConnectionState.DISCONNECTED

        # Serialization lock to prevent overlapping reconnection attempts
        self._reconnect_lock = asyncio.Lock()

        # Message tracking
        self.joined_channels = set()
        self.confirmed_channels = set()
        self.pending_joins = {}
        self.join_timeout = CHANNEL_JOIN_TIMEOUT
        self.max_join_attempts = MAX_JOIN_ATTEMPTS

        # Connection health monitoring (Twitch-specific)
        self.last_server_activity = 0  # Track when we last heard from server
        self.server_activity_timeout = SERVER_ACTIVITY_TIMEOUT
        self.last_ping_from_server = 0  # When server last sent us a PING
        self.expected_ping_interval = PING_EXPECTED_INTERVAL

        # Exponential backoff for reconnection attempts
        self.consecutive_failures = 0  # Track consecutive reconnection failures
        self.last_reconnect_attempt = 0  # Timestamp of last reconnection attempt
        self.connection_start_time = 0  # Track when connection attempts started

        # Message callbacks (can be sync or async)
        self.message_handler: Callable[[str, str, str], Any] | None = None
        self.color_change_handler: Callable[[str, str, str], Any] | None = None

        # Buffer for partial messages
        self.message_buffer = ""
        # Grace period after (re)connect where pending joins don't affect health
        self._join_grace_deadline: float | None = None

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
            success = await self._join_with_message_processing(channel)
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

    async def _join_with_message_processing(self, channel: str) -> bool:
        """Join channel while processing messages to get confirmation"""
        channel = channel.lower()

        if channel in self.confirmed_channels:
            logger.log_event(
                "irc",
                "join_already_confirmed",
                level=logging.DEBUG,
                user=self.username,
                channel=channel,
            )
            return True
        logger.log_event("irc", "join_start", user=self.username, channel=channel)

        try:
            # Send JOIN command
            await self._send_line(f"JOIN #{channel}")

            # Wait for join confirmation
            return await self._wait_for_join_confirmation(channel)

        except Exception as e:
            logger.log_event(
                "irc",
                "join_error",
                level=logging.ERROR,
                user=self.username,
                channel=channel,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def _wait_for_join_confirmation(self, channel: str) -> bool:
        """Wait for join confirmation by processing incoming messages"""
        start_time = time.time()
        message_buffer = ""

        while time.time() - start_time < ASYNC_IRC_JOIN_TIMEOUT:
            try:
                # Read data with timeout
                data = await self._read_join_data()
                if data is None:  # Connection lost
                    return False

                # Process the data
                decoded_data = data.decode("utf-8", errors="ignore")
                message_buffer = await self._process_incoming_data(
                    message_buffer, decoded_data
                )

                # Check if we got join confirmation
                if channel in self.confirmed_channels:
                    return self._finalize_channel_join(channel)

            except TimeoutError:
                # Timeout is expected - just continue checking
                continue
            except ConnectionResetError:
                self._log_connection_reset_error()
                return False
            except Exception as e:
                logger.log_event(
                    "irc",
                    "join_processing_error",
                    level=logging.ERROR,
                    user=self.username,
                    channel=channel,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return False

        # Join timeout
        self._log_join_timeout(channel)
        return False

    async def _read_join_data(self) -> bytes | None:
        """Read data during join process, return None if connection lost"""
        # Check if reader is available
        if not self.reader:
            logger.log_event(
                "irc", "join_no_reader", level=logging.ERROR, user=self.username
            )
            return None

        # Read with short timeout to allow checking for join confirmation
        data = await asyncio.wait_for(self.reader.read(4096), timeout=0.5)

        if not data:
            logger.log_event(
                "irc",
                "join_connection_lost",
                level=logging.ERROR,
                user=self.username,
            )
            return None

        return data

    def _finalize_channel_join(self, channel: str) -> bool:
        """Finalize channel join after confirmation"""
        if channel not in self.channels:
            self.channels.append(channel)
        logger.log_event("irc", "join_success", user=self.username, channel=channel)
        return True

    def _log_connection_reset_error(self):
        """Log connection reset error"""
        reset_msg = (
            f"❌ {self.username}: Connection reset by server - "
            "likely authentication failure"
        )
        logger.log_event(
            "irc",
            "connection_reset",
            level=logging.ERROR,
            user=self.username,
            message=reset_msg,
        )

    def _log_join_timeout(self, channel: str):
        """Log join timeout error"""
        logger.log_event(
            "irc",
            "join_timeout",
            level=logging.ERROR,
            user=self.username,
            channel=channel,
        )

    async def _send_line(self, message: str):
        """Send a line to the IRC server"""
        if self.writer:
            line = f"{message}\r\n"
            self.writer.write(line.encode("utf-8"))
            await self.writer.drain()

    async def join_channel(self, channel: str) -> bool:
        """Join a specific channel with timeout and retry logic"""
        channel = channel.lower()

        if channel in self.confirmed_channels:
            logger.log_event(
                "irc",
                "join_already_confirmed",
                level=logging.DEBUG,
                user=self.username,
                channel=channel,
            )
            return True

        # Track join attempt
        self.pending_joins[channel] = {
            "attempts": self.pending_joins.get(channel, {}).get("attempts", 0) + 1,
            "timestamp": time.time(),
        }

        attempts = self.pending_joins[channel]["attempts"]
        if attempts > self.max_join_attempts:
            logger.log_event(
                "irc",
                "join_max_attempts",
                level=logging.ERROR,
                user=self.username,
                channel=channel,
            )
            return False

        logger.log_event(
            "irc", "join_attempt", user=self.username, channel=channel, attempt=attempts
        )

        try:
            await self._send_line(f"JOIN #{channel}")

            # Wait for join confirmation with timeout
            start_time = time.time()
            while time.time() - start_time < ASYNC_IRC_JOIN_TIMEOUT:
                if channel in self.confirmed_channels:
                    self.pending_joins.pop(channel, None)
                    if channel not in self.channels:
                        self.channels.append(channel)
                    logger.log_event(
                        "irc", "join_success", user=self.username, channel=channel
                    )
                    return True
                await asyncio.sleep(0.1)  # Non-blocking sleep

            # Join timeout
            logger.log_event(
                "irc",
                "join_timeout",
                level=logging.WARNING,
                user=self.username,
                channel=channel,
            )
            self.pending_joins.pop(channel, None)
            return False

        except Exception as e:
            logger.log_event(
                "irc",
                "join_error",
                level=logging.ERROR,
                user=self.username,
                channel=channel,
                error=str(e),
                error_type=type(e).__name__,
            )
            self.pending_joins.pop(channel, None)
            return False

    async def listen(self):
        """Main async listening loop"""
        if not self._can_start_listening():
            return

        self._initialize_listening()

        try:
            while self.running and self.connected:
                should_break = await self._process_read_cycle()
                if should_break:
                    break
        finally:
            self._finalize_listening()

    def _can_start_listening(self) -> bool:
        """Check if we can start listening"""
        if not self.connected or not self.reader:
            logger.log_event(
                "irc", "listen_start_failed", level=logging.ERROR, user=self.username
            )
            return False
        return True

    def _initialize_listening(self):
        """Initialize the listening state"""
        logger.log_event("irc", "listener_start", user=self.username)
        self.running = True
        self.last_server_activity = time.time()

    async def _process_read_cycle(self) -> bool:
        """Process one read cycle. Returns True if listening should break."""
        try:
            return await self._handle_data_read()
        except TimeoutError:
            return self._handle_read_timeout()
        except Exception as e:
            logger.log_event(
                "irc",
                "connection_reset",
                level=logging.ERROR,
                user=self.username,
                error=str(e),
            )
            return True

    async def _handle_data_read(self) -> bool:
        """Handle reading data from the connection. Returns True if should break."""
        if not self.reader:
            logger.log_event(
                "irc", "no_reader", level=logging.ERROR, user=self.username
            )
            return True

        data = await asyncio.wait_for(
            self.reader.read(4096),
            timeout=ASYNC_IRC_READ_TIMEOUT,
        )

        if not data:
            logger.log_event(
                "irc", "connection_lost", level=logging.ERROR, user=self.username
            )
            self.connected = False
            return True

        # Process incoming data
        decoded_data = data.decode("utf-8", errors="ignore")
        self.message_buffer = await self._process_incoming_data(
            self.message_buffer, decoded_data
        )

        # Perform periodic checks
        return self._perform_periodic_checks()

    def _handle_read_timeout(self) -> bool:
        """Handle read timeout. Returns True if should break."""
        if self._is_connection_stale():
            logger.log_event(
                "irc", "connection_stale", level=logging.WARNING, user=self.username
            )
            self.connected = False
            return True
        return False

    def _finalize_listening(self):
        """Finalize the listening state"""
        self.running = False
        logger.log_event(
            "irc", "listener_stopped", level=logging.WARNING, user=self.username
        )
        if not self.writer or not self.reader:
            self.connected = False

    async def _process_incoming_data(self, buffer: str, new_data: str) -> str:
        """Process incoming IRC data and handle complete messages"""
        buffer += new_data

        # Update activity timestamp
        self.last_server_activity = time.time()

        # Process complete lines
        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)
            if line.strip():
                await self._handle_irc_message(line.strip())

        return buffer

    async def _handle_irc_message(self, raw_message: str):
        """Handle individual IRC messages"""
        # Debug: Log all incoming messages
        if not raw_message.startswith("PING"):
            logger.log_event(
                "irc",
                "raw",
                level=logging.DEBUG,
                user=self.username,
                raw=raw_message,
            )

        # Handle PINGs immediately
        if raw_message.startswith("PING"):
            await self._handle_ping(raw_message)
            return

        # Parse and handle other IRC messages
        prefix, command, params = self._parse_irc_message(raw_message)
        if not command:
            return

        # Handle different message types
        if command in ["366", "RPL_ENDOFNAMES"]:  # End of NAMES list
            self._handle_channel_confirmation(params)
        elif command == "PRIVMSG" and prefix:  # Only handle if prefix is not None
            await self._handle_privmsg(prefix, params)

    async def _handle_ping(self, raw_message: str):
        """Handle PING messages"""
        server = raw_message.split(":", 1)[1] if ":" in raw_message else "tmi.twitch.tv"
        pong = f"PONG :{server}"
        await self._send_line(pong)
        self.last_ping_from_server = time.time()

    def _parse_irc_message(self, raw_message: str) -> tuple[str | None, str, str]:
        """Parse IRC message format with IRCv3 tags"""
        raw_msg = raw_message

        # Remove IRCv3 tags if present (start with @)
        if raw_msg.startswith("@"):
            tag_end = raw_msg.find(" ")
            if tag_end != -1:
                raw_msg = raw_msg[tag_end + 1 :]  # Remove tags and the space

        parts = raw_msg.split(" ", 2)
        if len(parts) < 2:
            return None, "", ""

        prefix = parts[0] if parts[0].startswith(":") else None
        command = parts[1] if prefix else parts[0]
        params = parts[2] if len(parts) > 2 else ""

        return prefix, command, params

    def _handle_channel_confirmation(self, params: str):
        """Handle channel join confirmation messages"""
        if " #" in params:
            channel = params.split(" #")[1].split()[0].lower()
            self.confirmed_channels.add(channel)
            self.joined_channels.add(channel)

    async def _handle_privmsg(self, prefix: str, params: str):
        """Handle PRIVMSG (chat messages)"""
        # Parse and validate message components
        channel, message, username = self._parse_privmsg_components(prefix, params)
        if not channel or not message or not username:
            return

        # Log the message
        self._log_chat_message(username, channel, message)

        # Handle message with registered handlers
        await self._process_message_handlers(username, channel, message)

        # Handle color change commands
        await self._handle_color_change_command(username, channel, message)

    def _parse_privmsg_components(
        self, prefix: str, params: str
    ) -> tuple[str | None, str | None, str | None]:
        """Parse PRIVMSG components and return channel, message, username"""
        if not prefix or " :" not in params:
            logger.log_event(
                "irc",
                "privmsg_invalid_format",
                level=logging.WARNING,
                user=self.username,
                prefix=prefix,
                params=params,
            )
            return None, None, None

        # Parse channel and message
        channel_msg = params.split(" :", 1)
        if len(channel_msg) < 2:
            logger.log_event(
                "irc",
                "privmsg_parse_failed",
                level=logging.WARNING,
                user=self.username,
                params=params,
            )
            return None, None, None

        channel = channel_msg[0].strip().lstrip("#").lower()
        message = channel_msg[1]

        # Extract username from prefix (:username!username@username.tmi.twitch.tv)
        username = prefix.split("!")[0].lstrip(":") if "!" in prefix else "unknown"

        return channel, message, username

    def _log_chat_message(self, username: str, channel: str, message: str):
        """Log chat message with appropriate visibility"""
        is_bot_message = (
            username.lower() == self.username.lower() if self.username else False
        )
        if is_bot_message:
            logger.log_event(
                "irc",
                "privmsg",
                user=self.username,
                author=username,
                channel=channel,
                chat_message=message,
                self_message=True,
            )
        else:
            logger.log_event(
                "irc",
                "privmsg",
                level=logging.DEBUG,
                user=self.username,
                author=username,
                channel=channel,
                chat_message=message,
                self_message=False,
            )

    async def _process_message_handlers(
        self, username: str, channel: str, message: str
    ):
        """Process message through registered handlers"""
        if not self.message_handler:
            logger.log_event(
                "irc",
                "no_message_handler",
                level=logging.WARNING,
                user=self.username,
            )
            return

        logger.log_event(
            "irc",
            "dispatch_message_handler",
            level=logging.DEBUG,
            user=self.username,
            channel=channel,
            author=username,
        )

        try:
            # Check if handler is async and call appropriately
            if inspect.iscoroutinefunction(self.message_handler):
                await self.message_handler(username, channel, message)
            else:
                # For sync handlers, run in thread to avoid blocking
                task = asyncio.create_task(
                    asyncio.to_thread(self.message_handler, username, channel, message)
                )
                await task

            logger.log_event(
                "irc",
                "message_handler_complete",
                level=logging.DEBUG,
                user=self.username,
                channel=channel,
                author=username,
            )
        except Exception as e:
            logger.log_event(
                "irc",
                "connect_network_error",
                level=logging.ERROR,
                user=self.username,
                channel=channel,
                error=str(e),
            )

    async def _handle_color_change_command(
        self, username: str, channel: str, message: str
    ):
        """Handle color change commands"""
        if not message.startswith("/color ") or not self.color_change_handler:
            return

        try:
            task = asyncio.create_task(
                asyncio.to_thread(self.color_change_handler, username, channel, message)
            )
            await task
        except Exception as e:
            logger.log_event(
                "irc",
                "connect_network_error",
                level=logging.ERROR,
                user=self.username,
                channel=channel,
                error=str(e),
            )

    def _perform_periodic_checks(self) -> bool:
        """
        Perform periodic health checks - returns True if connection
        should be terminated
        """
        current_time = time.time()

        # Check for server activity timeout
        activity_timeout = self.server_activity_timeout
        if current_time - self.last_server_activity > activity_timeout:
            logger.log_event(
                "irc",
                "no_server_activity",
                level=logging.WARNING,
                user=self.username,
                timeout=self.server_activity_timeout,
            )
            return True

        # Check ping timeout (if we've received pings before)
        ping_timeout = self.expected_ping_interval * 1.5
        if (
            self.last_ping_from_server > 0
            and current_time - self.last_ping_from_server > ping_timeout
        ):
            time_since_ping = current_time - self.last_ping_from_server
            logger.log_event(
                "irc",
                "ping_timeout",
                level=logging.WARNING,
                user=self.username,
                time_since_ping=time_since_ping,
            )
            return True

        return False

    def _is_connection_stale(self) -> bool:
        """Check if connection appears stale (enhanced for early detection)"""
        current_time = time.time()
        time_since_activity = current_time - self.last_server_activity

        # More aggressive stale detection - warn at 25% of timeout for proactive recovery
        early_stale_threshold = self.server_activity_timeout * 0.25

        if time_since_activity > early_stale_threshold:
            # Log early warning for observability
            logger.log_event(
                "irc",
                "stale_early_warning",
                level=logging.DEBUG,
                user=self.username,
                time_since_activity=time_since_activity,
            )

        # Return true if we're beyond 50% of timeout (original behavior preserved)
        return time_since_activity > (self.server_activity_timeout / 2)

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

    async def force_reconnect(self) -> bool:
        """Force a reconnection (for external health checks) with race protection"""
        async with self._reconnect_lock:
            if not self.username or not self.token or not self.channels:
                logger.log_event(
                    "irc",
                    "reconnect_missing_details",
                    level=logging.ERROR,
                    user=self.username,
                )
                return False

            self._set_state(ConnectionState.RECONNECTING)
            logger.log_event(
                "irc", "force_reconnect", level=logging.WARNING, user=self.username
            )

            # Check if we need to wait due to exponential backoff
            now = time.time()
            time_since_last_attempt = now - self.last_reconnect_attempt
            backoff_delay = self._calculate_backoff_delay()

            if time_since_last_attempt < backoff_delay:
                remaining_wait = backoff_delay - time_since_last_attempt
                logger.log_event(
                    "irc",
                    "reconnect_backoff_wait",
                    level=logging.WARNING,
                    user=self.username,
                    remaining_wait=remaining_wait,
                    attempt=self.consecutive_failures + 1,
                )
                await asyncio.sleep(remaining_wait)

            # Store original channels before reconnecting (snapshot under lock)
            original_channels = self.channels.copy()

            # Disconnect first
            await self.disconnect()

            # Short delay before reconnecting
            await asyncio.sleep(RECONNECT_DELAY)

            # Update reconnection attempt tracking
            self.last_reconnect_attempt = time.time()
            self.consecutive_failures += 1

            # Reconnect with timeout
            channel = original_channels[0] if original_channels else ""
            try:
                success = await asyncio.wait_for(
                    self.connect(self.token, self.username, channel),
                    timeout=ASYNC_IRC_RECONNECT_TIMEOUT,
                )
            except TimeoutError:
                logger.log_event(
                    "irc",
                    "reconnect_timeout",
                    level=logging.ERROR,
                    user=self.username,
                    timeout=ASYNC_IRC_RECONNECT_TIMEOUT,
                )
                success = False

            if success:
                # Reset exponential backoff on successful reconnection
                self.consecutive_failures = 0

                # Reset ping timer after successful reconnection
                now = time.time()
                self.last_ping_from_server = now
                self.last_server_activity = now

                # Restore the original channels list but defer joining extras until listener runs
                self.channels = original_channels
                self._join_grace_deadline = time.time() + 30

                num_channels = len(self.channels)
                logger.log_event(
                    "irc",
                    "reconnect_success",
                    user=self.username,
                    extra_channels=num_channels - 1,
                )
            else:
                logger.log_event(
                    "irc",
                    "reconnect_failed",
                    level=logging.ERROR,
                    user=self.username,
                    attempt=self.consecutive_failures,
                )

            # Set final state based on success and health
            if success:
                # Check if reconnection was truly successful
                if self.is_healthy():
                    self._set_state(ConnectionState.READY)
                else:
                    self._set_state(ConnectionState.DEGRADED)
            else:
                self._set_state(ConnectionState.DISCONNECTED)

            return success

    def _calculate_backoff_delay(self) -> float:
        """Calculate exponential backoff delay with jitter"""
        if self.consecutive_failures == 0:
            return 0.0

        # Calculate exponential delay: base * multiplier^failures
        delay = BACKOFF_BASE_DELAY * (
            BACKOFF_MULTIPLIER ** (self.consecutive_failures - 1)
        )

        # Cap at maximum delay
        delay = min(delay, BACKOFF_MAX_DELAY)

        # Add jitter to avoid thundering herd
        # Use secrets for cryptographically secure random numbers
        jitter = (
            delay * BACKOFF_JITTER_FACTOR * (secrets.SystemRandom().random() * 2 - 1)
        )  # ±10% jitter
        delay += jitter

        return max(0.0, delay)  # Ensure non-negative

    def set_message_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the message handler callback (can be sync or async)"""
        self.message_handler = handler

    def set_color_change_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the color change handler callback (can be sync or async)"""
        self.color_change_handler = handler

    def get_connection_stats(self) -> dict:
        """Get connection statistics for health monitoring"""
        current_time = time.time()
        time_since_activity = current_time - self.last_server_activity
        return {
            "connected": self.connected,
            "running": self.running,
            "channels": list(self.channels),
            "confirmed_channels": list(self.confirmed_channels),
            "last_server_activity": self.last_server_activity,
            "last_ping_from_server": self.last_ping_from_server,
            "time_since_activity": time_since_activity,  # Key expected by bot.py
            "time_since_last_activity": time_since_activity,  # Alternative key
            "time_since_last_ping": (
                current_time - self.last_ping_from_server
                if self.last_ping_from_server > 0
                else 0
            ),
            "consecutive_failures": self.consecutive_failures,
            "pending_joins": len(self.pending_joins),
            "is_healthy": self.is_healthy(),  # Include health status
        }

    def is_healthy(self) -> bool:
        """Check if the IRC connection is healthy"""
        health_data = self.get_health_snapshot()
        return health_data["healthy"]

    def _check_basic_connection_health(self, reasons: list[str]) -> None:
        """Check basic connection state and add issues to reasons list"""
        if not self.connected:
            reasons.append("not_connected")
        if not self.running:
            reasons.append("not_running")
        if not self.reader or not self.writer:
            reasons.append("missing_streams")

    def _check_activity_health(
        self, reasons: list[str], current_time: float
    ) -> float | None:
        """Check activity timeouts and return time_since_activity"""
        time_since_activity = (
            current_time - self.last_server_activity
            if self.last_server_activity > 0
            else None
        )

        if time_since_activity is not None:
            # Early warning for idle connection (50% of timeout)
            if time_since_activity > (self.server_activity_timeout * 0.5):
                reasons.append("idle_warning")
            # Full stale detection
            if time_since_activity > self.server_activity_timeout:
                reasons.append("stale_activity")

        return time_since_activity

    def _check_ping_health(self, reasons: list[str], current_time: float) -> None:
        """Check ping timeout health"""
        if self.last_ping_from_server > 0:
            ping_timeout = self.expected_ping_interval * 1.5
            if current_time - self.last_ping_from_server > ping_timeout:
                reasons.append("ping_timeout")

    def _check_operational_health(self, reasons: list[str]) -> None:
        """Check operational health indicators"""
        if self.pending_joins:
            reasons.append("pending_joins")
        if self.consecutive_failures > 0:
            reasons.append("recent_failures")

    def get_health_snapshot(self) -> dict[str, Any]:
        """Return structured health info with detailed reasons"""
        reasons: list[str] = []
        current_time = time.time()

        # Check different health aspects
        self._check_basic_connection_health(reasons)
        time_since_activity = self._check_activity_health(reasons, current_time)
        self._check_ping_health(reasons, current_time)
        self._check_operational_health(reasons)
        # Suppress pending_joins penalty during grace period
        if (
            self._join_grace_deadline
            and current_time < self._join_grace_deadline
            and "pending_joins" in reasons
        ):
            reasons.remove("pending_joins")

        return {
            "username": self.username,
            "state": self.state.name,
            "connection_state": self.state.name,  # Backward compatibility alias
            "healthy": len(reasons) == 0,
            "reasons": reasons,
            "connected": self.connected,
            "running": self.running,
            "time_since_activity": time_since_activity,
            "time_since_ping": (
                current_time - self.last_ping_from_server
                if self.last_ping_from_server > 0
                else None
            ),
            "pending_joins": len(self.pending_joins),
            "consecutive_failures": self.consecutive_failures,
            "has_streams": self.reader is not None and self.writer is not None,
        }

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
