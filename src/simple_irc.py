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
        self.server = 'irc.chat.twitch.tv'
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
        self.server_activity_timeout = 300  # 5 minutes without any server activity = dead connection
        self.last_ping_from_server = 0  # When server last sent us a PING
        self.expected_ping_interval = 270  # Twitch typically pings every ~4.5 minutes
        
        # Client-initiated health checks
        self.last_client_ping_sent = 0  # When we last sent a PING to test connection
        self.last_pong_received = 0  # When we last received a PONG response
        self.client_ping_interval = 300  # Send client PING every 5 minutes
        self.pong_timeout = 15  # Wait 15 seconds for PONG response
        self.consecutive_ping_failures = 0
        self.max_consecutive_ping_failures = 3

    def connect(self, token: str, username: str, channel: str) -> bool:
        """Connect to Twitch IRC with the given credentials"""
        # Set connection details
        self.username = username.lower()
        self.token = token if token.startswith('oauth:') else f'oauth:{token}'
        self.channels = [channel.lower().replace('#', '')]

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.server, self.port))

            # Send authentication
            self.sock.send(f"PASS {self.token}\r\n".encode('utf-8'))
            self.sock.send(f"NICK {self.username}\r\n".encode('utf-8'))

            # Request capabilities
            self.sock.send("CAP REQ :twitch.tv/membership\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/tags\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/commands\r\n".encode('utf-8'))

            self.connected = True
            self.running = True  # Enable the listening loop
            print_log(f"✅ Connected to Twitch IRC as {self.username}", BColors.OKGREEN)
            return True

        except Exception as e:
            print_log(f"❌ IRC connection failed: {e}", BColors.FAIL)
            return False

    def set_message_handler(self, handler):
        """Set the message handler callback"""
        self.message_handler = handler

    def join_channel(self, channel: str):
        """Join a Twitch channel"""
        channel = channel.lower().replace('#', '')
        if self.sock and self.connected:
            self.sock.send(f"JOIN #{channel}\r\n".encode('utf-8'))
            self.joined_channels.add(channel)
            # Track pending join (or increment attempts if retrying)
            attempt = 1
            if channel in self.pending_joins:
                attempt = self.pending_joins[channel]['attempts'] + 1
            self.pending_joins[channel] = {'sent_at': time.time(), 'attempts': attempt}

    def _parse_message(self, raw_message: str) -> Optional[dict]:
        """Parse IRC message into components"""
        try:
            # Split line depending on presence of tags; unify variable extraction
            if raw_message.startswith('@'):
                parts = raw_message.split(' ', 3)
                if len(parts) < 4:
                    return None
                _, prefix, command, params = parts
            else:
                parts = raw_message.split(' ', 2)
                if len(parts) < 3:
                    return None
                prefix, command, params = parts

            sender = prefix.split('!')[0].replace(
                ':', '') if '!' in prefix else prefix.replace(
                ':', '')

            if command == 'PRIVMSG':
                channel_msg = params.split(' :', 1)
                if len(channel_msg) < 2:
                    return None
                channel = channel_msg[0].replace('#', '')
                message = channel_msg[1]
                return {
                    'sender': sender,
                    'channel': channel,
                    'message': message,
                    'command': command,
                    'raw': raw_message}
            if command == '366':  # RPL_ENDOFNAMES - successful join
                channel = params.split(' ')[1].replace('#', '')
                self.confirmed_channels.add(channel)
                self.pending_joins.pop(channel, None)
                print_log(
                    f"✅ {
                        self.username} successfully joined #{channel}",
                    BColors.OKGREEN)
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
        pong = line.replace('PING', 'PONG')
        self.sock.send(f"{pong}\r\n".encode('utf-8'))
        print_log("🏓 Responded to server PING", BColors.OKCYAN, debug_only=True)

    def _handle_pong(self, line: str):
        """Handle PONG responses (to our client-initiated PINGs)"""
        now = time.time()
        self.last_server_activity = now
        self.last_pong_received = now
        
        # Reset failure counter on successful PONG
        if self.last_client_ping_sent > 0:
            self.consecutive_ping_failures = 0
            print_log(f"🏓 Received PONG response: {line}", BColors.OKCYAN, debug_only=True)

    def _send_client_ping(self) -> bool:
        """Send a client-initiated PING to test connection health"""
        if not self.sock or not self.connected:
            return False
            
        try:
            ping_msg = f"PING :health_check_{int(time.time())}"
            self.sock.send(f"{ping_msg}\r\n".encode('utf-8'))
            self.last_client_ping_sent = time.time()
            print_log("🏓 Sent client health check PING", BColors.OKCYAN, debug_only=True)
            return True
        except Exception as e:
            print_log(f"❌ Failed to send client PING: {e}", BColors.FAIL)
            self.consecutive_ping_failures += 1
            return False

    def _check_connection_health(self) -> bool:
        """Check if connection is healthy based on Twitch server activity and client ping tests"""
        now = time.time()
        
        # Check when we last heard from server (any message)
        time_since_activity = now - self.last_server_activity
        if time_since_activity > self.server_activity_timeout:
            print_log(
                f"⚠️ {self.username}: No server activity for {time_since_activity:.1f}s "
                f"(threshold: {self.server_activity_timeout}s)",
                BColors.WARNING
            )
            return False
        
        # Check for too many consecutive client ping failures
        if self.consecutive_ping_failures >= self.max_consecutive_ping_failures:
            print_log(
                f"⚠️ {self.username}: Too many consecutive client ping failures ({self.consecutive_ping_failures})",
                BColors.WARNING
            )
            return False
        
        # Check if we have a pending PONG that's timed out
        if self.last_client_ping_sent > self.last_pong_received:
            time_since_ping = now - self.last_client_ping_sent
            if time_since_ping > self.pong_timeout:
                print_log(
                    f"⚠️ {self.username}: Client PING timeout ({time_since_ping:.1f}s since PING)",
                    BColors.WARNING
                )
                self.consecutive_ping_failures += 1
                return False
        
        # Check when server last sent us a PING (Twitch-specific)
        time_since_ping = now - self.last_ping_from_server
        if time_since_ping > self.expected_ping_interval and self.last_ping_from_server > 0:
            print_log(
                f"⚠️ {self.username}: No PING from server for {time_since_ping:.1f}s "
                f"(expected every ~{self.expected_ping_interval}s)",
                BColors.WARNING
            )
            return False
        
        # Send client ping if it's time for a health check
        time_since_client_ping = now - self.last_client_ping_sent
        if time_since_client_ping > self.client_ping_interval:
            if not self._send_client_ping():
                return False
        
        return True

    def _is_connection_stale(self) -> bool:
        """Check if connection appears to be stale (Twitch-specific)"""
        return not self._check_connection_health()

    def _handle_privmsg(self, parsed: dict):
        """Handle PRIVMSG messages"""
        sender = parsed['sender']
        channel = parsed['channel']
        message = parsed['message']

        # Log message - only show other users' messages in debug mode
        display_msg = message[:50] + ('...' if len(message) > 50 else '')
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
        
        if line.startswith('PING'):
            self._handle_ping(line)
            return
        
        if line.startswith('PONG'):
            self._handle_pong(line)
            return

        # Parse message
        parsed = self._parse_message(line)
        if parsed and parsed.get('command') == 'PRIVMSG':
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
            f"📡 IRC received data: {repr(data[:100])}{'...' if len(data) > 100 else ''}", 
            BColors.OKCYAN, debug_only=True
        )
        buffer += data

        while '\r\n' in buffer:
            line, buffer = buffer.split('\r\n', 1)
            if line:
                print_log(
                    f"📝 Processing IRC line: {repr(line)}",
                    BColors.OKGREEN,
                    debug_only=True
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
                data = self.sock.recv(4096).decode('utf-8', errors='ignore')
                if not data:
                    print_log("❌ IRC connection lost", BColors.FAIL)
                    break

                buffer = self._process_incoming_data(buffer, data)
                
                # Perform periodic checks
                if self._perform_periodic_checks():
                    print_log(
                        f"❌ {self.username}: Max connection failures reached, disconnecting",
                        BColors.FAIL
                    )
                    break

            except socket.timeout:
                if self._is_connection_stale():
                    print_log(f"❌ {self.username}: Connection appears stale", BColors.FAIL)
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
        if (now - info['sent_at']) < self.join_timeout:
            return False
        attempts = info['attempts']
        can_retry = attempts < self.max_join_attempts
        connected = self.sock and self.connected
        if can_retry and connected:
            print_log(
                f"⚠️ {
                    self.username} retrying join for #{channel} (attempt {
                    attempts +
                    1})",
                BColors.WARNING)
            try:
                self.sock.send(f"JOIN #{channel}\r\n".encode('utf-8'))
                info['sent_at'] = now
                info['attempts'] = attempts + 1
                return False  # Keep pending
            except Exception as e:
                print_log(
                    f"❌ {
                        self.username} failed to resend JOIN for #{channel}: {e}",
                    BColors.FAIL)
        elif can_retry and not connected:
            print_log(
                f"❌ {
                    self.username} cannot retry join for #{channel} (not connected)",
                BColors.FAIL)
        # Failure path
        print_log(
            f"❌ {
                self.username} failed to join #{channel} after {attempts} attempts (timeout)",
            BColors.FAIL)
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
            'connected': self.connected,
            'running': self.running,
            'last_server_activity': self.last_server_activity,
            'time_since_activity': now - self.last_server_activity,
            'last_ping_from_server': self.last_ping_from_server,
            'time_since_server_ping': now - self.last_ping_from_server if self.last_ping_from_server > 0 else 0,
            'last_client_ping_sent': self.last_client_ping_sent,
            'last_pong_received': self.last_pong_received,
            'time_since_client_ping': now - self.last_client_ping_sent if self.last_client_ping_sent > 0 else 0,
            'consecutive_ping_failures': self.consecutive_ping_failures,
            'is_healthy': self.is_healthy()
        }

    def force_reconnect(self) -> bool:
        """Force a reconnection (for external health checks)"""
        if not self.username or not self.token or not self.channels:
            print_log("❌ Cannot reconnect: missing connection details", BColors.FAIL)
            return False
        
        print_log(f"🔄 {self.username}: Forcing reconnection...", BColors.WARNING)
        
        # Disconnect first
        self.disconnect()
        
        # Short delay before reconnecting
        time.sleep(1)
        
        # Reconnect
        channel = self.channels[0] if self.channels else ""
        success = self.connect(self.token, self.username, channel)
        
        if success:
            # Re-join all channels after successful reconnection
            for channel in self.channels:
                self.join_channel(channel)
        
        return success
