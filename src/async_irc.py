"""
Async IRC client for Twitch - Pure async implementation
"""

import asyncio
import time
from typing import Any, Callable, Optional

from .colors import BColors
from .constants import (
    ASYNC_IRC_CONNECT_TIMEOUT,
    ASYNC_IRC_JOIN_TIMEOUT,
    ASYNC_IRC_READ_TIMEOUT,
    BACKOFF_BASE_DELAY,
    BACKOFF_JITTER_FACTOR,
    BACKOFF_MAX_DELAY,
    BACKOFF_MULTIPLIER,
    CHANNEL_JOIN_TIMEOUT,
    MAX_JOIN_ATTEMPTS,
    PING_EXPECTED_INTERVAL,
    RECONNECT_DELAY,
    SERVER_ACTIVITY_TIMEOUT,
)
from .utils import print_log


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
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
        self.connected = False

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

        # Message callbacks (can be sync or async)
        self.message_handler: Optional[Callable[[str, str, str], Any]] = None
        self.color_change_handler: Optional[Callable[[str, str, str], Any]] = None

        # Buffer for partial messages
        self.message_buffer = ""

    async def connect(self, token: str, username: str, channel: str) -> bool:
        """Connect to Twitch IRC with the given credentials"""
        # Set connection details
        self.username = username.lower()
        self.token = token if token.startswith("oauth:") else f"oauth:{token}"
        self.channels = [channel.lower()]

        try:
            print_log(
                f"🔗 {self.username}: Connecting to {self.server}:{self.port}...",
                BColors.OKCYAN,
            )

            # Async connection establishment
            print_log(
                f"🔗 {self.username}: Opening connection with timeout "
                f"{ASYNC_IRC_CONNECT_TIMEOUT}s",
                BColors.OKCYAN,
                debug_only=True,
            )
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.server, self.port),
                timeout=ASYNC_IRC_CONNECT_TIMEOUT,
            )
            print_log(
                f"🔗 {self.username}: Connection established, sending auth",
                BColors.OKCYAN,
                debug_only=True,
            )

            # Send authentication
            await self._send_line(f"PASS {self.token}")
            await self._send_line(f"NICK {self.username}")

            # Enable required capabilities for Twitch
            await self._send_line("CAP REQ :twitch.tv/membership")
            await self._send_line("CAP REQ :twitch.tv/tags")
            await self._send_line("CAP REQ :twitch.tv/commands")

            print_log(
                f"🔗 {self.username}: Auth sent, waiting 2s for processing",
                BColors.OKCYAN,
                debug_only=True,
            )
            # Wait for connection confirmation
            await asyncio.sleep(2)  # Give server time to process

            print_log(
                f"🔗 {self.username}: Attempting to join channel #{channel}",
                BColors.OKCYAN,
                debug_only=True,
            )
            # Start temporary message processing for join confirmation
            success = await self._join_with_message_processing(channel)
            if success:
                self.connected = True
                print_log(
                    f"✅ {self.username}: Connected and joined #{channel}",
                    BColors.OKGREEN,
                )
                return True
            else:
                print_log(
                    f"❌ {self.username}: Failed to join #{channel}", BColors.FAIL
                )
                await self.disconnect()
                return False

        except asyncio.TimeoutError:
            timeout_msg = (
                f"❌ {self.username}: Connection timeout after "
                f"{ASYNC_IRC_CONNECT_TIMEOUT}s"
            )
            print_log(timeout_msg, BColors.FAIL)
            await self.disconnect()
            return False
        except OSError as e:
            if "Connection reset by peer" in str(e):
                reset_msg = (
                    f"❌ {self.username}: Connection reset by server - "
                    "check token/username validity"
                )
                print_log(reset_msg, BColors.FAIL)
            else:
                print_log(f"❌ {self.username}: Network error: {e}", BColors.FAIL)
            await self.disconnect()
            return False
        except Exception as e:
            print_log(
                f"❌ {self.username}: Connection error: {type(e).__name__}: {e}",
                BColors.FAIL,
            )
            await self.disconnect()
            return False

    async def _join_with_message_processing(self, channel: str) -> bool:
        """Join channel while processing messages to get confirmation"""
        channel = channel.lower()

        if channel in self.confirmed_channels:
            print_log(
                f"ℹ️ {self.username}: Already in #{channel}",
                BColors.OKCYAN,
                debug_only=True,
            )
            return True

        print_log(f"🚪 {self.username}: Joining #{channel}...", BColors.OKCYAN)

        try:
            # Send JOIN command
            await self._send_line(f"JOIN #{channel}")

            # Process messages until we get join confirmation or timeout
            start_time = time.time()
            message_buffer = ""

            while time.time() - start_time < ASYNC_IRC_JOIN_TIMEOUT:
                try:
                    # Check if reader is available
                    if not self.reader:
                        print_log(
                            f"❌ {self.username}: No reader available during join",
                            BColors.FAIL,
                        )
                        return False

                    # Read with short timeout to allow checking for join confirmation
                    data = await asyncio.wait_for(self.reader.read(4096), timeout=0.5)

                    if not data:
                        print_log(
                            f"❌ {self.username}: Connection lost during join",
                            BColors.FAIL,
                        )
                        return False

                    # Process the data
                    decoded_data = data.decode("utf-8", errors="ignore")
                    message_buffer = await self._process_incoming_data(
                        message_buffer, decoded_data
                    )

                    # Check if we got join confirmation
                    if channel in self.confirmed_channels:
                        if channel not in self.channels:
                            self.channels.append(channel)
                        print_log(
                            f"✅ {self.username}: Successfully joined #{channel}",
                            BColors.OKGREEN,
                        )
                        return True

                except asyncio.TimeoutError:
                    # Timeout is expected - just continue checking
                    continue
                except ConnectionResetError:
                    reset_msg = (
                        f"❌ {self.username}: Connection reset by server - "
                        "likely authentication failure"
                    )
                    print_log(reset_msg, BColors.FAIL)
                    return False
                except Exception as e:
                    error_msg = f"❌ {self.username}: Error during join processing: {e}"
                    print_log(error_msg, BColors.FAIL)
                    return False

            # Join timeout
            timeout_msg = (
                f"⏰ {self.username}: Join timeout for #{channel} after "
                f"{ASYNC_IRC_JOIN_TIMEOUT}s"
            )
            print_log(timeout_msg, BColors.FAIL)
            return False

        except Exception as e:
            error_msg = f"❌ {self.username}: Error joining #{channel}: {e}"
            print_log(error_msg, BColors.FAIL)
            return False

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
            print_log(
                f"ℹ️ {self.username}: Already in #{channel}",
                BColors.OKCYAN,
                debug_only=True,
            )
            return True

        # Track join attempt
        self.pending_joins[channel] = {
            "attempts": self.pending_joins.get(channel, {}).get("attempts", 0) + 1,
            "timestamp": time.time(),
        }

        attempts = self.pending_joins[channel]["attempts"]
        if attempts > self.max_join_attempts:
            print_log(
                f"❌ {self.username}: Max join attempts reached for #{channel}",
                BColors.FAIL,
            )
            return False

        print_log(
            f"🚪 {self.username}: Joining #{channel} (attempt {attempts})...",
            BColors.OKCYAN,
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
                    print_log(
                        f"✅ {self.username}: Successfully joined #{channel}",
                        BColors.OKGREEN,
                    )
                    return True
                await asyncio.sleep(0.1)  # Non-blocking sleep

            # Join timeout
            print_log(
                f"⏰ {self.username}: Join timeout for #{channel}", BColors.WARNING
            )
            return False

        except Exception as e:
            print_log(
                f"❌ {self.username}: Error joining #{channel}: {e}", BColors.FAIL
            )
            return False

    async def listen(self):
        """Main async listening loop"""
        if not self.connected or not self.reader:
            print_log(
                f"❌ {self.username}: Cannot listen - not connected", BColors.FAIL
            )
            return

        print_log(
            f"👂 {self.username}: Starting async message listener...", BColors.OKCYAN
        )
        self.running = True

        # Initialize health monitoring
        now = time.time()
        self.last_server_activity = now

        try:
            while self.running and self.connected:
                try:
                    # Non-blocking read with timeout
                    data = await asyncio.wait_for(
                        self.reader.read(4096),
                        # 1 second timeout for responsiveness
                        timeout=ASYNC_IRC_READ_TIMEOUT,
                    )

                    if not data:
                        print_log(
                            f"❌ {self.username}: IRC connection lost", BColors.FAIL
                        )
                        break

                    # Process incoming data
                    decoded_data = data.decode("utf-8", errors="ignore")
                    self.message_buffer = await self._process_incoming_data(
                        self.message_buffer, decoded_data
                    )

                    # Perform periodic checks
                    if self._perform_periodic_checks():
                        break

                except asyncio.TimeoutError:
                    # Timeout is normal - allows for periodic checks
                    if self._is_connection_stale():
                        print_log(
                            f"💀 {self.username}: Connection appears stale",
                            BColors.WARNING,
                        )
                        break
                    continue

                except Exception as e:
                    print_log(f"❌ {self.username}: Listen error: {e}", BColors.FAIL)
                    break

        finally:
            self.running = False
            print_log(f"🔇 {self.username}: Stopped listening", BColors.WARNING)

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
            print_log(f"🔍 IRC: {raw_message}", BColors.HEADER, debug_only=True)

        # Handle PINGs immediately
        if raw_message.startswith("PING"):
            server = (
                raw_message.split(":", 1)[1] if ":" in raw_message else "tmi.twitch.tv"
            )
            pong = f"PONG :{server}"
            await self._send_line(pong)
            self.last_ping_from_server = time.time()
            return

        # Parse IRC message format with IRCv3 tags: [@tags] [:prefix] <command>
        # [params] [:trailing]
        raw_msg = raw_message

        # Remove IRCv3 tags if present (start with @)
        if raw_msg.startswith("@"):
            # Find the end of tags (space after tags section)
            tag_end = raw_msg.find(" ")
            if tag_end != -1:
                raw_msg = raw_msg[tag_end + 1:]  # Remove tags and the space

        parts = raw_msg.split(" ", 2)
        if len(parts) < 2:
            return

        prefix = parts[0] if parts[0].startswith(":") else None
        command = parts[1] if prefix else parts[0]
        params = parts[2] if len(parts) > 2 else ""

        # Handle channel confirmations
        if command in ["366", "RPL_ENDOFNAMES"]:  # End of NAMES list
            if " #" in params:
                channel = params.split(" #")[1].split()[0].lower()
                self.confirmed_channels.add(channel)
                self.joined_channels.add(channel)

        # Handle chat messages
        elif command == "PRIVMSG" and prefix:  # Only handle if prefix is not None
            await self._handle_privmsg(prefix, params)

    async def _handle_privmsg(self, prefix: str, params: str):
        """Handle PRIVMSG (chat messages)"""
        if not prefix or " :" not in params:
            print_log(
                f"🐛 Invalid PRIVMSG format: prefix='{prefix}', params='{params}'",
                BColors.WARNING,
            )
            return

        # Parse channel and message
        channel_msg = params.split(" :", 1)
        if len(channel_msg) < 2:
            print_log(f"🐛 Failed to parse PRIVMSG: '{params}'", BColors.WARNING)
            return

        channel = channel_msg[0].strip().lstrip("#").lower()
        message = channel_msg[1]

        # Extract username from prefix (:username!username@username.tmi.twitch.tv)
        username = prefix.split("!")[0].lstrip(":") if "!" in prefix else "unknown"

        # Show bot's own messages in normal mode, others only in debug mode
        is_bot_message = (
            username.lower() == self.username.lower() if self.username else False
        )
        print_log(
            f"💬 Received message from {username} in #{channel}: {message}",
            BColors.OKCYAN,
            debug_only=not is_bot_message,
        )

        # Call message handler if set
        if self.message_handler:
            print_log(
                f"🔄 Calling message handler for {username} in #{channel}",
                BColors.OKCYAN,
                debug_only=True,
            )
            try:
                # Check if handler is async and call appropriately
                import inspect

                if inspect.iscoroutinefunction(self.message_handler):
                    await self.message_handler(username, channel, message)
                else:
                    # For sync handlers, run in thread to avoid blocking
                    task = asyncio.create_task(
                        asyncio.to_thread(
                            self.message_handler, username, channel, message
                        )
                    )
                    await task
                print_log(
                    f"✅ Message handler completed for {username} in #{channel}",
                    BColors.OKGREEN,
                    debug_only=True,
                )
            except Exception as e:
                print_log(f"❌ Message handler error: {e}", BColors.FAIL)
                import traceback

                print_log(f"❌ Full traceback: {traceback.format_exc()}", BColors.FAIL)
        else:
            print_log("⚠️ No message handler set!", BColors.WARNING)

        # Check for color change commands
        if message.startswith("/color ") and self.color_change_handler:
            try:
                task = asyncio.create_task(
                    asyncio.to_thread(
                        self.color_change_handler, username, channel, message
                    )
                )
                await task
            except Exception as e:
                print_log(f"❌ Color change handler error: {e}", BColors.FAIL)

    def _perform_periodic_checks(self) -> bool:
        """
        Perform periodic health checks - returns True if connection
        should be terminated
        """
        current_time = time.time()

        # Check for server activity timeout
        activity_timeout = self.server_activity_timeout
        if current_time - self.last_server_activity > activity_timeout:
            print_log(
                f"💀 {
                    self.username}: No server activity for {
                    self.server_activity_timeout}s",
                BColors.WARNING,
            )
            return True

        # Check ping timeout (if we've received pings before)
        ping_timeout = self.expected_ping_interval * 1.5
        if (
            self.last_ping_from_server > 0
            and current_time - self.last_ping_from_server > ping_timeout
        ):
            time_since_ping = current_time - self.last_ping_from_server
            ping_msg = (
                f"🏓 {self.username}: Ping timeout - "
                f"last ping {time_since_ping:.0f}s ago"
            )
            print_log(ping_msg, BColors.WARNING)
            return True

        return False

    def _is_connection_stale(self) -> bool:
        """Check if connection appears stale"""
        current_time = time.time()
        return (current_time - self.last_server_activity) > (
            self.server_activity_timeout / 2
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
                print_log(
                    f"❌ {self.username}: Error closing connection: {e}", BColors.FAIL
                )
            finally:
                self.writer = None
                self.reader = None

        # Reset state
        self.joined_channels.clear()
        self.confirmed_channels.clear()
        self.pending_joins.clear()
        self.message_buffer = ""

        print_log(f"📡 {self.username}: Disconnected", BColors.WARNING)

    async def force_reconnect(self) -> bool:
        """Force a reconnection (for external health checks)"""
        if not self.username or not self.token or not self.channels:
            print_log("❌ Cannot reconnect: missing connection details", BColors.FAIL)
            return False

        print_log(f"🔄 {self.username}: Forcing async reconnection...", BColors.WARNING)

        # Check if we need to wait due to exponential backoff
        now = time.time()
        time_since_last_attempt = now - self.last_reconnect_attempt
        backoff_delay = self._calculate_backoff_delay()

        if time_since_last_attempt < backoff_delay:
            remaining_wait = backoff_delay - time_since_last_attempt
            print_log(
                f"⏳ {
                    self.username}: Waiting {
                    remaining_wait:.1f}s due to exponential backoff "
                f"(attempt {
                    self.consecutive_failures +
                    1})",
                BColors.WARNING,
            )
            await asyncio.sleep(remaining_wait)

        # Store original channels before reconnecting
        original_channels = self.channels.copy()

        # Disconnect first
        await self.disconnect()

        # Short delay before reconnecting
        await asyncio.sleep(RECONNECT_DELAY)

        # Update reconnection attempt tracking
        self.last_reconnect_attempt = time.time()
        self.consecutive_failures += 1

        # Reconnect
        channel = original_channels[0] if original_channels else ""
        success = await self.connect(self.token, self.username, channel)

        if success:
            # Reset exponential backoff on successful reconnection
            self.consecutive_failures = 0

            # Reset ping timer after successful reconnection
            now = time.time()
            self.last_ping_from_server = now
            self.last_server_activity = now

            # Restore the original channels list and re-join all channels
            self.channels = original_channels
            # Skip first channel (already joined in connect)
            for channel in self.channels[1:]:
                await self.join_channel(channel)

            num_channels = len(self.channels)
            success_msg = (
                f"✅ {self.username}: Async reconnected and rejoined "
                f"{num_channels} channels"
            )
            print_log(success_msg, BColors.OKGREEN)
        else:
            failure_msg = (
                f"❌ {self.username}: Async reconnection failed "
                f"(attempt {self.consecutive_failures})"
            )
            print_log(failure_msg, BColors.FAIL)

        return success

    def _calculate_backoff_delay(self) -> float:
        """Calculate exponential backoff delay with jitter"""
        import random

        if self.consecutive_failures == 0:
            return 0.0

        # Calculate exponential delay: base * multiplier^failures
        delay = BACKOFF_BASE_DELAY * (
            BACKOFF_MULTIPLIER ** (self.consecutive_failures - 1)
        )

        # Cap at maximum delay
        delay = min(delay, BACKOFF_MAX_DELAY)

        # Add jitter to avoid thundering herd
        jitter = (
            delay * BACKOFF_JITTER_FACTOR * (random.random() * 2 - 1)
        )  # ±10% jitter
        delay += jitter

        return max(0.0, delay)  # Ensure non-negative

    def set_message_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the message handler callback (can be sync or async)"""
        self.message_handler = handler

    def set_color_change_handler(self, handler: Callable[[str, str, str], Any]):
        """Set the color change handler callback (can be sync or async)"""
        self.color_change_handler = handler
