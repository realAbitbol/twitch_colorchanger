"""
Simple IRC client for Twitch - based on working implementation
"""

import socket
import time
from typing import Optional

from .colors import BColors
from .utils import print_log


class SimpleTwitchIRC:
    """Simple IRC client for Twitch using raw sockets - based on working version"""

    def __init__(self):
        # IRC connection details (set during connect)
        self.username = None
        self.token = None
        self.channels = []
        self.message_handler = None

        # IRC connection
        self.server = "irc.chat.twitch.tv"
        self.port = 6667
        self.sock = None
        self.running = False
        self.connected = False

        # Message tracking
        self.joined_channels = set()
        self.confirmed_channels = set()
        self.pending_joins = {}
        self.join_timeout = 30  # seconds to wait for RPL_ENDOFNAMES before retry/fail
        self.max_join_attempts = 2

        # Connection health monitoring (Twitch-specific)
        self.last_server_activity = 0  # Track when we last heard from server
        self.server_activity_timeout = (
            300  # 5 minutes without any server activity = dead connection
        )
        self.last_ping_from_server = 0  # When server last sent us a PING
        self.expected_ping_interval = 600  # Twitch pings every ~10 minutes

    def connect(self, token: str, username: str, channel: str) -> bool:
        """Connect to Twitch IRC with the given credentials"""
        # Set connection details
        self.username = username.lower()
        self.token = token if token.startswith("oauth:") else f"oauth:{token}"

        # Initialize channels list with the provided channel if not already set
        if not self.channels:
            self.channels = [channel.lower().replace("#", "")]

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.server, self.port))

            # Send authentication
            self.sock.send(f"PASS {self.token}\r\n".encode("utf-8"))
            self.sock.send(f"NICK {self.username}\r\n".encode("utf-8"))

            # Request capabilities
            self.sock.send("CAP REQ :twitch.tv/membership\r\n".encode("utf-8"))
            self.sock.send("CAP REQ :twitch.tv/tags\r\n".encode("utf-8"))
            self.sock.send("CAP REQ :twitch.tv/commands\r\n".encode("utf-8"))

            self.connected = True
            self.running = True  # Enable the listening loop

            # Initialize ping timers
            now = time.time()
            self.last_server_activity = now
            self.last_ping_from_server = now

            print_log(f"✅ Connected to Twitch IRC as {self.username}", BColors.OKGREEN)
            return True

        except Exception as e:
            print_log(f"❌ IRC connection failed: {e}", BColors.FAIL)
            return False

    def set_message_handler(self, handler):
        """Set the message handler callback"""
        self.message_handler = handler

    def join_channel(self, channel: str, _is_retry: bool = False):
        """Join a Twitch channel"""
        channel = channel.lower().replace("#", "")

        # Don't join if already confirmed
        if channel in self.confirmed_channels:
            if not _is_retry:  # Only log for user calls, not internal retries
                print_log(
                    f"ℹ️ {self.username}: Already joined #{channel}, skipping",
                    BColors.OKBLUE,
                )
            return

        # Don't join if already pending (unless it's an internal retry)
        if channel in self.pending_joins and not _is_retry:
            print_log(
                f"ℹ️ {self.username}: Join already pending for #{channel}, skipping",
                BColors.OKBLUE,
            )
            return

        if self.sock and self.connected:
            self.sock.send(f"JOIN #{channel}\r\n".encode("utf-8"))
            self.joined_channels.add(channel)
            # Track pending join (or increment attempts if retrying)
            if _is_retry and channel in self.pending_joins:
                self.pending_joins[channel]["attempts"] += 1
                self.pending_joins[channel]["sent_at"] = time.time()
            else:
                self.pending_joins[channel] = {"sent_at": time.time(), "attempts": 1}

    def _parse_message(self, raw_message: str) -> Optional[dict]:
        """Parse IRC message into components"""
        try:
            # Split line depending on presence of tags; unify variable extraction
            if raw_message.startswith("@"):
                parts = raw_message.split(" ", 3)
                if len(parts) < 4:
                    return None
                _, prefix, command, params = parts
            else:
                parts = raw_message.split(" ", 2)
                if len(parts) < 3:
                    return None
                prefix, command, params = parts

            sender = (
                prefix.split("!")[0].replace(":", "")
                if "!" in prefix
                else prefix.replace(":", "")
            )

            if command == "PRIVMSG":
                channel_msg = params.split(" :", 1)
                if len(channel_msg) < 2:
                    return None
                channel = channel_msg[0].replace("#", "")
                message = channel_msg[1]
                return {
                    "sender": sender,
                    "channel": channel,
                    "message": message,
                    "command": command,
                    "raw": raw_message,
                }
            if command == "366":  # RPL_ENDOFNAMES - successful join
                channel = params.split(" ")[1].replace("#", "")
                self.confirmed_channels.add(channel)
                self.pending_joins.pop(channel, None)
                print_log(
                    f"✅ {
                        self.username} successfully joined #{channel}",
                    BColors.OKGREEN,
                )
            return None
        except Exception as e:
            print_log(f"⚠️ Parse error: {e}", BColors.WARNING)
            return None

    def _handle_ping(self, line: str):
        """Handle PING messages from Twitch server"""
        # Update activity timestamps
        now = time.time()
        self.last_server_activity = now
        self.last_ping_from_server = now

        # Respond with PONG (standard IRC behavior)
        pong = line.replace("PING", "PONG")
        self.sock.send(f"{pong}\r\n".encode("utf-8"))
        print_log(
            f"🏓 {self.username}: Received PING from server, responded with PONG",
            BColors.OKCYAN,
        )

    def _check_connection_health(self) -> bool:
        """Check if connection is healthy based on Twitch server activity"""
        now = time.time()

        # Check when we last heard from server (any message)
        time_since_activity = now - self.last_server_activity
        if time_since_activity > self.server_activity_timeout:
            print_log(
                f"⚠️ {self.username}: No server activity for "
                f"{time_since_activity:.1f}s "
                f"(threshold: {self.server_activity_timeout}s)",
                BColors.WARNING,
            )
            return False

        # Check when server last sent us a PING (Twitch-specific)
        time_since_ping = now - self.last_ping_from_server
        if (
            time_since_ping > self.expected_ping_interval
            and self.last_ping_from_server > 0
        ):
            print_log(
                f"⚠️ {self.username}: No PING from server for {time_since_ping:.1f}s "
                f"(expected every ~{self.expected_ping_interval}s)",
                BColors.WARNING,
            )
            return False

        return True

    def _is_connection_stale(self) -> bool:
        """Check if connection appears to be stale (Twitch-specific)"""
        return not self._check_connection_health()

    def _handle_privmsg(self, parsed: dict):
        """Handle PRIVMSG messages"""
        sender = parsed["sender"]
        channel = parsed["channel"]
        message = parsed["message"]

        # Log message - only show other users' messages in debug mode
        display_msg = message[:50] + ("..." if len(message) > 50 else "")
        is_own_message = sender.lower() == self.username.lower()
        debug_only = not is_own_message  # Only show other users' messages in debug mode
        color = BColors.OKCYAN if is_own_message else BColors.OKBLUE

        print_log(f"#{channel} - {sender}: {display_msg}", color, debug_only=debug_only)

        # Call message handler
        if self.message_handler:
            self.message_handler(sender, channel, message)

    def _process_line(self, line: str):
        """Process a single IRC line"""
        # Update server activity timestamp for any message
        self.last_server_activity = time.time()

        if line.startswith("PING"):
            self._handle_ping(line)
            return

        # Parse message
        parsed = self._parse_message(line)
        if parsed and parsed.get("command") == "PRIVMSG":
            self._handle_privmsg(parsed)

    def _perform_periodic_checks(self):
        """Perform periodic health and timeout checks"""
        # Check for join timeouts
        self._check_join_timeouts()

        # Simple health check - if connection seems stale, signal for disconnection
        if self._is_connection_stale():
            print_log(f"❌ {self.username}: Connection appears stale", BColors.FAIL)
            return True  # Signal disconnection needed

        return False

    def _process_incoming_data(self, buffer: str, data: str) -> str:
        """Process incoming IRC data and return updated buffer"""
        print_log(
            f"📡 IRC received data: {repr(data[:100])}"
            f"{'...' if len(data) > 100 else ''}",
            BColors.OKCYAN,
            debug_only=True,
        )
        buffer += data

        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)
            if line:
                print_log(
                    f"📝 Processing IRC line: {repr(line)}",
                    BColors.OKGREEN,
                    debug_only=True,
                )
                self._process_line(line)

        return buffer

    def listen(self):
        """Main listening loop"""
        buffer = ""
        print_log("🎧 IRC listening loop started", BColors.OKBLUE, debug_only=True)

        # Initialize health monitoring
        now = time.time()
        self.last_server_activity = now

        while self.running and self.connected:
            try:
                data = self.sock.recv(4096).decode("utf-8", errors="ignore")
                if not data:
                    print_log("❌ IRC connection lost", BColors.FAIL)
                    break

                buffer = self._process_incoming_data(buffer, data)

                # Perform periodic checks
                if self._perform_periodic_checks():
                    # _perform_periodic_checks already logged the reason
                    break

            except socket.timeout:
                if self._is_connection_stale():
                    print_log(
                        f"❌ {self.username}: Connection appears stale", BColors.FAIL
                    )
                    break
                continue
            except Exception as e:
                print_log(f"❌ Listen error: {e}", BColors.FAIL)
                break

    def _check_join_timeouts(self):
        """Check pending channel joins for timeouts and retry or fail."""
        if not self.pending_joins:
            return
        now = time.time()
        to_remove = []
        for channel, info in self.pending_joins.items():
            if self._handle_single_join_timeout(channel, info, now):
                to_remove.append(channel)
        for ch in to_remove:
            self.pending_joins.pop(ch, None)

    def _handle_single_join_timeout(self, channel: str, info: dict, now: float) -> bool:
        """Handle timeout logic for a single pending JOIN.
        Returns True if the channel should be removed from pending joins."""
        # Still waiting
        if (now - info["sent_at"]) < self.join_timeout:
            return False
        attempts = info["attempts"]
        can_retry = attempts < self.max_join_attempts
        connected = self.sock and self.connected
        if can_retry and connected:
            print_log(
                f"⚠️ {
                    self.username} retrying join for #{channel} (attempt {
                    attempts +
                    1})",
                BColors.WARNING,
            )
            try:
                self.sock.send(f"JOIN #{channel}\r\n".encode("utf-8"))
                info["sent_at"] = now
                info["attempts"] = attempts + 1
                return False  # Keep pending
            except Exception as e:
                print_log(
                    f"❌ {
                        self.username} failed to resend JOIN for #{channel}: {e}",
                    BColors.FAIL,
                )
        elif can_retry and not connected:
            print_log(
                f"❌ {
                    self.username} cannot retry join for #{channel} (not connected)",
                BColors.FAIL,
            )
        # Failure path
        print_log(
            f"❌ {self.username} failed to join #{channel} after "
            f"{attempts} attempts (timeout)",
            BColors.FAIL,
        )
        return True

    def disconnect(self):
        """Disconnect from IRC"""
        self.running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except (OSError, AttributeError):
                pass
            self.sock = None

        # Clear channel state on disconnect
        self.joined_channels.clear()
        self.confirmed_channels.clear()
        self.pending_joins.clear()

        print_log("🔌 Disconnected from IRC", BColors.WARNING)

    def is_healthy(self) -> bool:
        """Check if the IRC connection is healthy"""
        if not self.connected or not self.sock:
            return False

        return self._check_connection_health()

    def get_connection_stats(self) -> dict:
        """Get connection health statistics"""
        now = time.time()
        return {
            "connected": self.connected,
            "running": self.running,
            "last_server_activity": self.last_server_activity,
            "time_since_activity": now - self.last_server_activity,
            "last_ping_from_server": self.last_ping_from_server,
            "time_since_server_ping": (
                now - self.last_ping_from_server
                if self.last_ping_from_server > 0
                else 0
            ),
            "is_healthy": self.is_healthy(),
        }

    def force_reconnect(self) -> bool:
        """Force a reconnection (for external health checks)"""
        if not self.username or not self.token or not self.channels:
            print_log("❌ Cannot reconnect: missing connection details", BColors.FAIL)
            return False

        print_log(f"🔄 {self.username}: Forcing reconnection...", BColors.WARNING)

        # Store original channels before reconnecting
        original_channels = self.channels.copy()

        # Disconnect first
        self.disconnect()

        # Short delay before reconnecting
        time.sleep(1)

        # Reconnect
        channel = original_channels[0] if original_channels else ""
        success = self.connect(self.token, self.username, channel)

        if success:
            # Reset ping timer after successful reconnection
            now = time.time()
            self.last_ping_from_server = now
            self.last_server_activity = now

            # Restore the original channels list and re-join all channels
            self.channels = original_channels
            for channel in self.channels:
                self.join_channel(channel)

            print_log(
                f"✅ {self.username}: Reconnected and rejoined {len(self.channels)} channels",
                BColors.OKGREEN,
            )

        return success
