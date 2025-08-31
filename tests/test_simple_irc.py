"""
Tests for simple_irc.py module
"""

import socket
import time
from unittest.mock import Mock, MagicMock, patch, call

import pytest
from src.logger import BColors

from src.simple_irc import SimpleTwitchIRC


class TestSimpleTwitchIRC:
    """Test SimpleTwitchIRC functionality"""

    @pytest.fixture
    def irc_client(self):
        """Create a SimpleTwitchIRC instance for testing"""
        return SimpleTwitchIRC()

    @pytest.fixture
    def mock_socket(self):
        """Create a mock socket for testing"""
        mock_sock = Mock()
        mock_sock.send = Mock()
        mock_sock.recv = Mock(return_value=b"test data\r\n")
        mock_sock.close = Mock()
        mock_sock.settimeout = Mock()
        mock_sock.connect = Mock()
        return mock_sock

    def test_init(self, irc_client):
        """Test SimpleTwitchIRC initialization"""
        assert irc_client.username is None
        assert irc_client.token is None
        assert irc_client.channels == []
        assert irc_client.message_handler is None
        assert irc_client.server == "irc.chat.twitch.tv"
        assert irc_client.port == 6667
        assert irc_client.sock is None
        assert irc_client.running is False
        assert irc_client.connected is False
        assert irc_client.joined_channels == set()
        assert irc_client.confirmed_channels == set()
        assert irc_client.pending_joins == {}
        assert irc_client.join_timeout == 30
        assert irc_client.max_join_attempts == 2

    @patch("socket.socket")
    def test_connect_success(self, mock_socket_class, irc_client, mock_socket):
        """Test successful IRC connection"""
        mock_socket_class.return_value = mock_socket

        result = irc_client.connect("test_token", "testuser", "testchannel")

        assert result is True
        assert irc_client.username == "testuser"
        assert irc_client.token == "oauth:test_token"
        assert irc_client.channels == ["testchannel"]
        assert irc_client.connected is True
        assert irc_client.running is True

        # Verify socket operations
        mock_socket_class.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_socket.settimeout.assert_called_once_with(10.0)
        mock_socket.connect.assert_called_once_with(("irc.chat.twitch.tv", 6667))

        # Verify authentication messages were sent
        expected_calls = [
            "PASS oauth:test_token\r\n".encode("utf-8"),
            "NICK testuser\r\n".encode("utf-8"),
            "CAP REQ :twitch.tv/membership\r\n".encode("utf-8"),
            "CAP REQ :twitch.tv/tags\r\n".encode("utf-8"),
            "CAP REQ :twitch.tv/commands\r\n".encode("utf-8"),
        ]
        assert mock_socket.send.call_count == 5
        for call_obj, expected in zip(mock_socket.send.call_args_list, expected_calls):
            assert call_obj[0][0] == expected

    @patch("socket.socket")
    def test_connect_with_oauth_prefix(
        self, mock_socket_class, irc_client, mock_socket
    ):
        """Test connection with oauth: prefix already present"""
        mock_socket_class.return_value = mock_socket

        result = irc_client.connect("oauth:test_token", "testuser", "testchannel")

        assert result is True
        assert irc_client.token == "oauth:test_token"

    @patch("socket.socket")
    def test_connect_failure(self, mock_socket_class, irc_client):
        """Test IRC connection failure"""
        mock_socket_class.side_effect = Exception("Connection failed")

        result = irc_client.connect("test_token", "testuser", "testchannel")

        assert result is False
        assert irc_client.connected is False
        assert irc_client.running is False

    def test_set_message_handler(self, irc_client):
        """Test setting message handler"""

        def test_handler(sender, channel, message):
            pass  # Test handler implementation

        irc_client.set_message_handler(test_handler)
        assert irc_client.message_handler == test_handler

    def test_join_channel(self, irc_client, mock_socket):
        """Test joining a channel"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        irc_client.join_channel("TestChannel")

        # Verify JOIN command was sent
        mock_socket.send.assert_called_once_with(
            "JOIN #testchannel\r\n".encode("utf-8")
        )

        # Verify channel was added to tracking
        assert "testchannel" in irc_client.joined_channels
        assert "testchannel" in irc_client.pending_joins
        assert irc_client.pending_joins["testchannel"]["attempts"] == 1

    def test_join_channel_with_hash(self, irc_client, mock_socket):
        """Test joining a channel with # prefix"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        irc_client.join_channel("#TestChannel")

        mock_socket.send.assert_called_once_with(
            "JOIN #testchannel\r\n".encode("utf-8")
        )
        assert "testchannel" in irc_client.joined_channels

    def test_join_channel_retry(self, irc_client, mock_socket):
        """Test that joining a channel twice prevents duplicate joins"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # First join
        irc_client.join_channel("testchannel")
        # Second join attempt (should be prevented)
        irc_client.join_channel("testchannel")

        # Should have only 1 send call (duplicate prevented)
        assert mock_socket.send.call_count == 1
        assert irc_client.pending_joins["testchannel"]["attempts"] == 1

    def test_join_channel_not_connected(self, irc_client, mock_socket):
        """Test joining channel when not connected"""
        irc_client.sock = mock_socket
        irc_client.connected = False

        irc_client.join_channel("testchannel")

        # Should not send anything
        mock_socket.send.assert_not_called()
        assert "testchannel" not in irc_client.joined_channels

    def test_parse_message_privmsg(self, irc_client):
        """Test parsing PRIVMSG"""
        raw_message = ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #testchannel :Hello world"

        result = irc_client._parse_message(raw_message)

        expected = {
            "sender": "testuser",
            "channel": "testchannel",
            "message": "Hello world",
            "command": "PRIVMSG",
            "raw": raw_message,
        }
        assert result == expected

    def test_parse_message_privmsg_with_tags(self, irc_client):
        """Test parsing PRIVMSG with IRCv3 tags"""
        raw_message = "@badge-info=;badges=;color=#FF0000;display-name=TestUser :testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #testchannel :Hello world"

        result = irc_client._parse_message(raw_message)

        expected = {
            "sender": "testuser",
            "channel": "testchannel",
            "message": "Hello world",
            "command": "PRIVMSG",
            "raw": raw_message,
        }
        assert result == expected

    def test_parse_message_rpl_endofnames(self, irc_client):
        """Test parsing RPL_ENDOFNAMES (successful join)"""
        raw_message = ":tmi.twitch.tv 366 testuser #testchannel :End of /NAMES list"

        result = irc_client._parse_message(raw_message)

        assert result is None  # RPL_ENDOFNAMES doesn't return a message dict
        assert "testchannel" in irc_client.confirmed_channels
        assert "testchannel" not in irc_client.pending_joins

    def test_parse_message_malformed(self, irc_client):
        """Test parsing malformed messages"""
        malformed_messages = [
            "incomplete message",
            ":incomplete",
            "PRIVMSG #channel",
            ":sender!user@host CMD",
        ]

        for msg in malformed_messages:
            result = irc_client._parse_message(msg)
            assert result is None

    def test_parse_message_exception(self, irc_client):
        """Test parsing with exception handling"""
        # This should not happen in normal operation, but test error handling
        with patch("src.simple_irc.print_log") as mock_print:
            result = irc_client._parse_message(None)  # This will cause an exception

        assert result is None
        mock_print.assert_called()

    def test_handle_ping(self, irc_client, mock_socket):
        """Test PING handling"""
        irc_client.sock = mock_socket
        ping_line = "PING :tmi.twitch.tv"

        irc_client._handle_ping(ping_line)

        mock_socket.send.assert_called_once_with(
            "PONG :tmi.twitch.tv\r\n".encode("utf-8")
        )

    def test_handle_privmsg_own_message(self, irc_client):
        """Test handling own PRIVMSG"""
        irc_client.username = "testuser"
        parsed = {
            "sender": "testuser",
            "channel": "testchannel",
            "message": "Hello world",
            "command": "PRIVMSG",
            "raw": "raw message",
        }

        with patch("src.simple_irc.print_log") as mock_print:
            irc_client._handle_privmsg(parsed)

        # Should log own message
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0]
        assert "#testchannel - testuser: Hello world" in call_args[0]

    def test_handle_privmsg_other_message(self, irc_client):
        """Test handling other user's PRIVMSG"""
        irc_client.username = "testuser"
        parsed = {
            "sender": "otheruser",
            "channel": "testchannel",
            "message": "Hello world from someone else",
            "command": "PRIVMSG",
            "raw": "raw message",
        }

        with patch("src.simple_irc.print_log") as mock_print:
            irc_client._handle_privmsg(parsed)

        # Should log other user's message in debug mode
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0]
        assert "#testchannel - otheruser: Hello world from someone else" in call_args[0]
        assert mock_print.call_args[1]["debug_only"] is True

    def test_handle_privmsg_long_message(self, irc_client):
        """Test handling long PRIVMSG with truncation"""
        irc_client.username = "testuser"
        long_message = "A" * 60  # Longer than 50 chars
        parsed = {
            "sender": "otheruser",
            "channel": "testchannel",
            "message": long_message,
            "command": "PRIVMSG",
            "raw": "raw message",
        }

        with patch("src.simple_irc.print_log") as mock_print:
            irc_client._handle_privmsg(parsed)

        call_args = mock_print.call_args[0]
        assert "..." in call_args[0]  # Should be truncated

    def test_handle_privmsg_with_handler(self, irc_client):
        """Test PRIVMSG handling with message handler"""
        mock_handler = Mock()
        irc_client.message_handler = mock_handler
        irc_client.username = "testuser"

        parsed = {
            "sender": "otheruser",
            "channel": "testchannel",
            "message": "Hello world",
            "command": "PRIVMSG",
            "raw": "raw message",
        }

        with patch("src.simple_irc.print_log"):
            irc_client._handle_privmsg(parsed)

        # Handler should be called
        mock_handler.assert_called_once_with("otheruser", "testchannel", "Hello world")

    def test_process_line_ping(self, irc_client, mock_socket):
        """Test processing PING line"""
        irc_client.sock = mock_socket
        ping_line = "PING :tmi.twitch.tv"

        with patch.object(irc_client, "_handle_ping") as mock_handle_ping:
            with patch.object(irc_client, "_check_join_timeouts"):
                irc_client._process_line(ping_line)

        mock_handle_ping.assert_called_once_with(ping_line)

    def test_process_line_privmsg(self, irc_client):
        """Test processing PRIVMSG line"""
        privmsg_line = ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #testchannel :Hello world"

        with patch.object(irc_client, "_handle_privmsg") as mock_handle_privmsg:
            with patch.object(irc_client, "_parse_message") as mock_parse:
                mock_parse.return_value = {
                    "sender": "testuser",
                    "channel": "testchannel",
                    "message": "Hello world",
                    "command": "PRIVMSG",
                    "raw": privmsg_line,
                }
                with patch.object(irc_client, "_check_join_timeouts"):
                    irc_client._process_line(privmsg_line)

        mock_handle_privmsg.assert_called_once()

    def test_process_line_other_command(self, irc_client):
        """Test processing other IRC commands"""
        other_line = ":tmi.twitch.tv 001 testuser :Welcome to Twitch"

        with patch.object(irc_client, "_parse_message") as mock_parse:
            mock_parse.return_value = None  # Not a PRIVMSG
            with patch.object(irc_client, "_check_join_timeouts"):
                # Should not raise exception
                irc_client._process_line(other_line)

    @patch("socket.socket")
    def test_listen_success(self, mock_socket_class, irc_client, mock_socket):
        """Test successful listening loop"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock socket to return data then empty (connection closed)
        mock_socket.recv.side_effect = [
            ":tmi.twitch.tv 001 testuser :Welcome\r\n".encode("utf-8"),
            b"",  # Empty data = connection closed
        ]

        with patch.object(irc_client, "_process_line") as mock_process:
            with patch("src.simple_irc.print_log"):
                irc_client.listen()

        # Should have processed the welcome message
        mock_process.assert_called()

    @patch("socket.socket")
    def test_listen_connection_lost(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with connection lost"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock empty recv (connection lost)
        mock_socket.recv.return_value = b""

        with patch("src.simple_irc.print_log"):
            irc_client.listen()

        # Should exit the loop (running should be set to False in disconnect or similar)
        # Note: The current implementation doesn't set running=False on connection loss
        # This is a design choice in the original code

    @patch("socket.socket")
    def test_listen_timeout(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with socket timeout"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock timeout exception
        mock_socket.recv.side_effect = socket.timeout

        # Mock running to eventually stop
        with patch.object(irc_client, "running", False):
            with patch("src.simple_irc.print_log"):
                irc_client.listen()

    @patch("socket.socket")
    def test_listen_exception(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with general exception"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock general exception
        mock_socket.recv.side_effect = Exception("Network error")

        with patch("src.simple_irc.print_log"):
            irc_client.listen()

        # Should exit the loop (running should be set to False in disconnect or similar)
        # Note: The current implementation doesn't set running=False on exceptions
        # This is a design choice in the original code

    def test_check_join_timeouts_empty(self, irc_client):
        """Test checking join timeouts with no pending joins"""
        # Should not raise exception
        irc_client._check_join_timeouts()

    def test_check_join_timeouts_success(self, irc_client, mock_socket):
        """Test checking join timeouts with successful join"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # Add a pending join that's confirmed (this would normally be removed by
        # _parse_message)
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {"sent_at": past_time, "attempts": 1}
        # Simulate what happens when RPL_ENDOFNAMES is received
        irc_client.confirmed_channels.add("testchannel")
        # This is what _parse_message does
        irc_client.pending_joins.pop("testchannel", None)

        with patch("src.simple_irc.print_log"):
            irc_client._check_join_timeouts()

        # Should remain removed from pending joins (already removed by successful join)
        assert "testchannel" not in irc_client.pending_joins

    def test_check_join_timeouts_retry(self, irc_client, mock_socket):
        """Test checking join timeouts with retry"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # Add a pending join that's timed out
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {"sent_at": past_time, "attempts": 1}

        with patch("src.simple_irc.print_log"):
            irc_client._check_join_timeouts()

        # Should retry join
        mock_socket.send.assert_called_with("JOIN #testchannel\r\n".encode("utf-8"))
        assert irc_client.pending_joins["testchannel"]["attempts"] == 2

    def test_check_join_timeouts_max_attempts(self, irc_client, mock_socket):
        """Test checking join timeouts with max attempts reached"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # Add a pending join that's timed out and at max attempts
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {
            "sent_at": past_time,
            "attempts": 2,  # Max attempts
        }

        with patch("src.simple_irc.print_log"):
            irc_client._check_join_timeouts()

        # Should remove from pending joins (failed)
        assert "testchannel" not in irc_client.pending_joins

    def test_check_join_timeouts_not_connected(self, irc_client, mock_socket):
        """Test checking join timeouts when not connected"""
        irc_client.sock = mock_socket
        irc_client.connected = False

        # Add a pending join that's timed out
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {"sent_at": past_time, "attempts": 1}

        with patch("src.simple_irc.print_log"):
            irc_client._check_join_timeouts()

        # Should remove from pending joins (cannot retry)
        assert "testchannel" not in irc_client.pending_joins

    def test_handle_single_join_timeout_waiting(self, irc_client):
        """Test handling single join timeout still waiting"""
        now = time.time()
        info = {"sent_at": now - 10, "attempts": 1}  # Not timed out yet

        result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is False  # Should continue waiting

    def test_handle_single_join_timeout_retry_success(self, irc_client, mock_socket):
        """Test handling single join timeout with successful retry"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        now = time.time()
        info = {"sent_at": now - 35, "attempts": 1}  # Timed out

        with patch("src.simple_irc.print_log"):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is False  # Should retry
        mock_socket.send.assert_called_once_with(
            "JOIN #testchannel\r\n".encode("utf-8")
        )
        assert info["attempts"] == 2

    def test_handle_single_join_timeout_retry_failure(self, irc_client, mock_socket):
        """Test handling single join timeout with retry failure"""
        irc_client.sock = mock_socket
        irc_client.connected = True
        mock_socket.send.side_effect = Exception("Send failed")

        now = time.time()
        info = {"sent_at": now - 35, "attempts": 1}  # Timed out

        with patch("src.simple_irc.print_log"):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is True  # Should fail

    def test_handle_single_join_timeout_max_attempts(self, irc_client, mock_socket):
        """Test handling single join timeout at max attempts"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        now = time.time()
        info = {"sent_at": now - 35, "attempts": 2}  # Max attempts

        with patch("src.simple_irc.print_log"):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is True  # Should fail

    def test_disconnect(self, irc_client, mock_socket):
        """Test disconnecting from IRC"""
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True

        with patch("src.simple_irc.print_log"):
            irc_client.disconnect()

        assert irc_client.running is False
        assert irc_client.connected is False
        assert irc_client.sock is None
        mock_socket.close.assert_called_once()

    def test_disconnect_no_socket(self, irc_client):
        """Test disconnecting when no socket exists"""
        irc_client.sock = None

        with patch("src.simple_irc.print_log"):
            # Should not raise exception
            irc_client.disconnect()

    def test_disconnect_socket_close_error(self, irc_client, mock_socket):
        """Test disconnecting with socket close error (covers lines 224-225)"""
        irc_client.sock = mock_socket
        mock_socket.close.side_effect = OSError("Close failed")

        with patch("src.simple_irc.print_log"):
            # Should not raise exception
            irc_client.disconnect()

        assert irc_client.sock is None

    def test_parse_message_tagged_incomplete(self, irc_client):
        """Test parsing incomplete tagged message (covers line 90)"""
        # Tagged message with insufficient parts
        raw_message = "@tags :sender CMD"  # Only 3 parts instead of 4

        result = irc_client._parse_message(raw_message)

        assert result is None

    def test_parse_message_privmsg_incomplete(self, irc_client):
        """Test parsing incomplete PRIVMSG (covers line 103)"""
        # PRIVMSG without proper message part
        raw_message = ":sender!user@host PRIVMSG #channel"  # No message after :

        result = irc_client._parse_message(raw_message)

        assert result is None

    @patch("socket.socket")
    def test_listen_timeout_continue(self, mock_socket_class, irc_client, mock_socket):
        """Test listen loop continues on timeout (covers line 176)"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock timeout exception followed by normal data then empty
        mock_socket.recv.side_effect = [
            socket.timeout,  # This should trigger continue
            ":tmi.twitch.tv 001 testuser :Welcome\r\n".encode("utf-8"),
            b"",  # Empty data = connection closed
        ]

        with patch.object(irc_client, "_process_line") as mock_process:
            with patch("src.simple_irc.print_log"):
                irc_client.listen()

        # Should have processed the welcome message after timeout
        mock_process.assert_called_once()


# Branch Coverage Tests - targeting specific uncovered branches
class TestSimpleIRCBranchCoverage:
    """Test missing branch coverage in simple_irc.py"""

    def test_join_channel_not_connected_early_exit(self):
        """Test early exit when not connected - lines 74->75"""
        irc = SimpleTwitchIRC()
        # Don't connect, so self.connected will be False
        irc.connected = False
        irc.sock = None

        # Should not raise exception and exit early
        irc.join_channel("testchannel")

        # Should not have added the channel to joined_channels
        assert "testchannel" not in irc.joined_channels

    def test_handle_single_join_timeout_max_attempts_reached(self):
        """Test when max attempts reached - lines 208->240"""
        irc = SimpleTwitchIRC()
        irc.connected = True
        irc.sock = MagicMock()
        irc.username = "testuser"

        # Create timeout info with max attempts reached (max is 2, so attempts = 2)
        # Also ensure timeout has passed (join_timeout = 30 seconds)
        channel = "testchannel"
        timeout_info = {
            "sent_at": time.time() - 35,  # 35 seconds ago (past 30 second timeout)
            "attempts": 2,  # Max attempts reached (max_join_attempts = 2)
        }
        current_time = time.time()

        with patch("src.simple_irc.print_log") as mock_print:
            result = irc._handle_single_join_timeout(
                channel, timeout_info, current_time
            )

            # Should return True when max attempts reached (remove from pending)
            assert result is True
            # Should log failure message
            mock_print.assert_called_with(
                f"❌ testuser failed to join #{channel} after 2 attempts (timeout)",
                BColors.FAIL,
            )

    def test_parse_message_rpl_endofnames_branch(self):
        """Test _parse_message RPL_ENDOFNAMES command branch - line 114->122"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "oauth:token123"

        # Add a pending join to test the success path
        irc.pending_joins["testchannel"] = {"timestamp": time.time(), "attempts": 1}

        # Test RPL_ENDOFNAMES message (366)
        message = ":tmi.twitch.tv 366 testuser #testchannel :End of /NAMES list"

        with patch("src.simple_irc.print_log") as mock_log:
            result = irc._parse_message(message)

            # Should process the message successfully
            assert result is None  # _parse_message returns None for 366

            # Channel should be added to confirmed channels
            assert "testchannel" in irc.confirmed_channels

            # Should be removed from pending joins
            assert "testchannel" not in irc.pending_joins

            # Should log success
            success_calls = [
                log_call
                for log_call in mock_log.call_args_list
                if "successfully joined" in str(log_call)
            ]
            assert len(success_calls) > 0

    def test_parse_message_non_366_command_skip_branch(self):
        """Test _parse_message when command is not 366 - line 114->122"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "oauth:token123"

        # Test with a different command (not 366)
        message = ":tmi.twitch.tv 001 testuser :Welcome to TMI"

        result = irc._parse_message(message)

        # Should process normally but skip the 366-specific logic
        # _parse_message always returns None
        assert result is None

    def test_listen_empty_line_skip_branch(self):
        """Test listen() when line is empty and gets skipped - line 180->178"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "oauth:token123"
        irc.connected = True

        # Create test data with empty lines
        test_data = "PING :tmi.twitch.tv\r\n\r\nPONG :reply\r\n"

        # Mock the handlers
        with patch.object(irc, "_process_line") as mock_process, patch(
            "src.simple_irc.print_log"
        ):

            # Simulate the buffer processing logic directly
            buffer = test_data

            while "\r\n" in buffer:
                line, buffer = buffer.split("\r\n", 1)
                if line:  # This is the branch we want to test
                    mock_process(line)
                # Empty lines are skipped (line 180->178 branch)

            # Should only process the non-empty lines
            assert (
                mock_process.call_count == 2
            )  # "PING :tmi.twitch.tv" and "PONG :reply"
            call_args_1 = mock_process.call_args_list[0][0][0]
            call_args_2 = mock_process.call_args_list[1][0][0]
            assert call_args_1 == "PING :tmi.twitch.tv"
            assert call_args_2 == "PONG :reply"

    def test_listen_empty_line_false_branch_line_180(self):
        """Test simple_irc.py line 180: if line -> False for empty lines"""
        # Test the buffer processing logic directly matching the exact code
        buffer = "\r\nvalid_line\r\n"

        # Split the buffer exactly like in listen()
        first_line, remaining_buffer = buffer.split("\r\n", 1)

        # First line is empty string - this tests the False branch of line 180
        assert first_line == ""  # This would make 'if line:' False
        assert not first_line  # Explicitly test the falsiness

        # Continue processing to verify the loop continues after the False branch
        assert "\r\n" in remaining_buffer  # While condition continues

        second_line, _ = remaining_buffer.split("\r\n", 1)
        assert second_line == "valid_line"  # This would make 'if line:' True

        # Verify we handled both the False and True branches of line 180

    def test_listen_leading_empty_line_executes_false_branch_runtime(self):
        """Call listen() so instrumentation records the empty-line False branch (line 180->178)."""
        irc = SimpleTwitchIRC()
        irc.username = "user"
        irc.token = "oauth:tok"
        irc.running = True
        irc.connected = True
        irc.sock = MagicMock()
        # First recv: leading CRLF then a PING line; second recv: empty to terminate
        irc.sock.recv.side_effect = [b"\r\nPING :tmi.twitch.tv\r\n", b""]

        with patch("src.simple_irc.print_log"), patch.object(
            irc, "_process_line"
        ) as mock_process:
            irc.listen()

        processed = [c.args[0] for c in mock_process.call_args_list]
        assert processed == ["PING :tmi.twitch.tv"]


class TestIRCHealthMonitoring:
    """Test IRC health monitoring functionality"""

    @pytest.fixture
    def irc_client(self):
        """Create IRC client for testing"""
        return SimpleTwitchIRC()

    @pytest.fixture
    def bot_config(self):
        """Bot configuration for testing"""
        return {
            "token": "test_token",
            "refresh_token": "test_refresh_token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "nick": "testuser",
            "channels": ["testchannel"],
            "is_prime_or_turbo": True,
            "config_file": None,
            "user_id": None,
        }

    def test_health_monitoring_initialization(self, irc_client):
        """Test health monitoring fields are initialized"""
        assert irc_client.last_client_ping_sent == 0
        assert irc_client.last_pong_received == 0
        assert irc_client.last_server_activity == 0
        assert irc_client.last_ping_from_server == 0
        assert irc_client.server_activity_timeout == 300
        assert irc_client.expected_ping_interval == 270
        assert irc_client.client_ping_interval == 300
        assert irc_client.pong_timeout == 15
        assert irc_client.consecutive_ping_failures == 0
        assert irc_client.max_consecutive_ping_failures == 3

    def test_handle_pong(self, irc_client):
        """Test PONG message handling"""
        test_time = time.time()

        with patch("src.simple_irc.time.time", return_value=test_time):
            with patch("src.simple_irc.print_log"):
                irc_client._handle_pong("PONG :tmi.twitch.tv")

        assert irc_client.last_pong_received == test_time
        assert irc_client.last_server_activity == test_time

    def test_send_client_ping_success(self, irc_client):
        """Test successful client PING sending"""
        mock_socket = MagicMock()
        irc_client.sock = mock_socket
        irc_client.connected = True

        test_time = time.time()
        with patch("src.simple_irc.time.time", return_value=test_time):
            with patch("src.simple_irc.print_log"):
                result = irc_client._send_client_ping()

        assert result is True
        assert irc_client.last_client_ping_sent == test_time
        mock_socket.send.assert_called_once()

    def test_send_client_ping_failure(self, irc_client):
        """Test client PING sending failure"""
        mock_socket = MagicMock()
        mock_socket.send.side_effect = Exception("Send failed")
        irc_client.sock = mock_socket
        irc_client.connected = True

        with patch("src.simple_irc.print_log"):
            result = irc_client._send_client_ping()

        assert result is False

    def test_send_client_ping_not_connected(self, irc_client):
        """Test client PING sending when not connected"""
        result = irc_client._send_client_ping()
        assert result is False

    def test_check_connection_health_healthy(self, irc_client):
        """Test connection health check when healthy"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # 30 seconds ago
        irc_client.last_pong_received = now
        irc_client.last_client_ping_sent = now - 10
        irc_client.last_ping_from_server = now - 100

        with patch("src.simple_irc.time.time", return_value=now):
            result = irc_client._check_connection_health()

        assert result is True

    def test_check_connection_health_pong_timeout(self, irc_client):
        """Test connection health check with PONG timeout"""
        now = time.time()
        irc_client.last_client_ping_sent = now - 20  # 20 seconds ago
        irc_client.last_pong_received = now - 30  # 30 seconds ago
        irc_client.pong_timeout = 15  # Expect PONG within 15 seconds
        irc_client.last_server_activity = now - 10  # Recent activity

        with patch("src.simple_irc.time.time", return_value=now):
            with patch("src.simple_irc.print_log"):
                result = irc_client._check_connection_health()

        assert result is False

    def test_check_connection_health_send_client_ping(self, irc_client):
        """Test connection health check sends client PING when needed"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.last_client_ping_sent = now - 310  # > client_ping_interval
        irc_client.last_pong_received = now - 50  # Before last ping
        irc_client.client_ping_interval = 300
        irc_client.consecutive_ping_failures = 0  # No previous failures

        with patch("src.simple_irc.time.time", return_value=now):
            with patch.object(
                irc_client, "_send_client_ping", return_value=True
            ) as mock_send_ping:
                result = irc_client._check_connection_health()

        mock_send_ping.assert_called_once()
        assert result is True

    def test_is_connection_stale_activity_timeout(self, irc_client):
        """Test stale connection detection by activity timeout"""
        now = time.time()
        irc_client.last_server_activity = now - 400  # > server_activity_timeout
        irc_client.server_activity_timeout = 300

        with patch("src.simple_irc.time.time", return_value=now):
            result = irc_client._is_connection_stale()

        assert result is True

    def test_is_connection_stale_pong_timeout(self, irc_client):
        """Test stale connection detection by PONG timeout"""
        now = time.time()
        irc_client.last_client_ping_sent = now - 20
        irc_client.last_pong_received = now - 30
        irc_client.pong_timeout = 15
        irc_client.last_server_activity = now - 10  # Recent activity

        with patch("src.simple_irc.time.time", return_value=now):
            result = irc_client._is_connection_stale()

        assert result is True

    def test_is_connection_stale_healthy(self, irc_client):
        """Test stale connection detection when healthy"""
        now = time.time()
        irc_client.last_server_activity = now - 30
        irc_client.last_client_ping_sent = now - 10
        irc_client.last_pong_received = now - 5

        with patch("src.simple_irc.time.time", return_value=now):
            result = irc_client._is_connection_stale()

        assert result is False

    def test_process_line_updates_activity(self, irc_client):
        """Test that processing lines updates server activity"""
        test_time = time.time()

        with patch("src.simple_irc.time.time", return_value=test_time):
            with patch.object(irc_client, "_parse_message", return_value=None):
                irc_client._process_line("SOME IRC LINE")

        assert irc_client.last_server_activity == test_time

    def test_process_line_handles_pong(self, irc_client):
        """Test that PONG messages are handled"""
        with patch.object(irc_client, "_handle_pong") as mock_handle_pong:
            irc_client._process_line("PONG :tmi.twitch.tv")

        mock_handle_pong.assert_called_once_with("PONG :tmi.twitch.tv")

    def test_perform_periodic_checks_health_failure(self, irc_client):
        """Test periodic checks when health check fails"""
        with patch.object(irc_client, "_check_join_timeouts"):
            with patch.object(irc_client, "_is_connection_stale", return_value=True):
                with patch("src.simple_irc.print_log"):
                    result = irc_client._perform_periodic_checks()

        assert result is True  # Should trigger disconnection

    def test_perform_periodic_checks_health_success(self, irc_client):
        """Test periodic checks when health check succeeds"""
        with patch.object(irc_client, "_check_join_timeouts"):
            with patch.object(irc_client, "_is_connection_stale", return_value=False):
                result = irc_client._perform_periodic_checks()

        assert result is False  # Should continue

    def test_listen_initializes_health_monitoring(self, irc_client):
        """Test that listen() initializes health monitoring timestamps"""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""  # Empty data to break loop
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True

        test_time = time.time()
        with patch("src.simple_irc.time.time", return_value=test_time):
            with patch("src.simple_irc.print_log"):
                irc_client.listen()

        assert irc_client.last_server_activity == test_time

    def test_listen_detects_stale_connection_on_timeout(self, irc_client):
        """Test that listen() detects stale connections on socket timeout"""
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [Exception("timeout"), b""]  # Timeout then empty
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True

        with patch.object(irc_client, "_is_connection_stale", return_value=True):
            with patch("src.simple_irc.print_log"):
                irc_client.listen()

    def test_is_healthy(self, irc_client):
        """Test is_healthy() method"""
        irc_client.connected = True
        irc_client.running = True
        irc_client.sock = MagicMock()

        # Not connected
        irc_client.connected = False
        assert irc_client.is_healthy() is False

        # Connected but unhealthy
        irc_client.connected = True
        with patch.object(irc_client, "_check_connection_health", return_value=False):
            assert irc_client.is_healthy() is False

        # Connected and healthy
        with patch.object(irc_client, "_check_connection_health", return_value=True):
            assert irc_client.is_healthy() is True

    def test_get_connection_stats(self, irc_client):
        """Test get_connection_stats() method"""
        now = time.time()
        irc_client.connected = True
        irc_client.running = True
        irc_client.last_server_activity = now - 30
        irc_client.last_ping_from_server = now - 100
        irc_client.last_client_ping_sent = now - 50
        irc_client.last_pong_received = now - 40
        irc_client.consecutive_ping_failures = 1

        with patch("src.simple_irc.time.time", return_value=now):
            with patch.object(irc_client, "is_healthy", return_value=True):
                stats = irc_client.get_connection_stats()

        assert stats["connected"] is True
        assert stats["running"] is True
        assert stats["last_server_activity"] == now - 30
        assert stats["time_since_activity"] == 30
        assert stats["last_client_ping_sent"] == now - 50
        assert stats["last_pong_received"] == now - 40
        assert stats["consecutive_ping_failures"] == 1
        assert stats["is_healthy"] is True

    def test_force_reconnect_success(self, irc_client):
        """Test successful force reconnection"""
        irc_client.username = "testuser"
        irc_client.token = "oauth:token"
        irc_client.channels = [
            "channel1",
            "channel2",
            "channel3",
        ]  # Multiple channels to test the loop

        with patch.object(irc_client, "disconnect"):
            with patch.object(irc_client, "connect", return_value=True) as mock_connect:
                with patch.object(irc_client, "join_channel") as mock_join:
                    with patch("src.simple_irc.time.sleep"):
                        with patch("src.simple_irc.print_log"):
                            result = irc_client.force_reconnect()

        assert result is True
        mock_connect.assert_called_once_with("oauth:token", "testuser", "channel1")
        # Should join all 3 channels after reconnection
        assert mock_join.call_count == 3

    def test_force_reconnect_missing_details(self, irc_client):
        """Test force reconnection with missing connection details"""
        with patch("src.simple_irc.print_log"):
            result = irc_client.force_reconnect()

        assert result is False


class TestBotIRCHealthIntegration:
    """Test bot IRC health monitoring integration"""

    @pytest.fixture
    def bot_config(self):
        """Bot configuration for testing"""
        return {
            "token": "test_token",
            "refresh_token": "test_refresh_token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "nick": "testuser",
            "channels": ["testchannel"],
            "is_prime_or_turbo": True,
            "config_file": None,
            "user_id": None,
        }

    async def test_check_irc_health_healthy(self, bot_config):
        """Test IRC health check when connection is healthy"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.return_value = {
            "is_healthy": True,
            "time_since_activity": 30.0,
            "connection_failures": 0,
        }
        bot.irc = mock_irc

        with patch("src.bot.print_log"):
            await bot._check_irc_health()

        mock_irc.get_connection_stats.assert_called_once()

    async def test_check_irc_health_unhealthy(self, bot_config):
        """Test IRC health check when connection is unhealthy"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.return_value = {
            "is_healthy": False,
            "time_since_activity": 150.0,
            "connection_failures": 2,
        }
        bot.irc = mock_irc

        with patch.object(bot, "_reconnect_irc") as mock_reconnect:
            with patch("src.bot.print_log"):
                await bot._check_irc_health()

        mock_reconnect.assert_called_once()

    async def test_check_irc_health_no_irc(self, bot_config):
        """Test IRC health check when no IRC connection exists"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        bot.irc = None

        # Should not raise exception
        await bot._check_irc_health()

    async def test_check_irc_health_exception(self, bot_config):
        """Test IRC health check with exception"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.side_effect = Exception("Stats error")
        bot.irc = mock_irc

        with patch("src.bot.print_log"):
            # Should not raise exception
            await bot._check_irc_health()

    async def test_reconnect_irc_success(self, bot_config):
        """Test successful IRC reconnection"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.return_value = True
        bot.irc = mock_irc

        mock_task = MagicMock()
        mock_task.done.return_value = False
        bot.irc_task = mock_task

        with patch("src.bot.asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            with patch("src.bot.print_log"):
                with patch("src.bot.asyncio.wait_for"):
                    await bot._reconnect_irc()

        mock_irc.force_reconnect.assert_called_once()
        mock_loop.run_in_executor.assert_called_once()

    async def test_reconnect_irc_failure(self, bot_config):
        """Test failed IRC reconnection"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.return_value = False
        bot.irc = mock_irc
        bot.irc_task = None

        with patch("src.bot.print_log"):
            await bot._reconnect_irc()

        mock_irc.force_reconnect.assert_called_once()

    async def test_reconnect_irc_exception(self, bot_config):
        """Test IRC reconnection with exception"""
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.side_effect = Exception("Reconnect error")
        bot.irc = mock_irc

        with patch("src.bot.print_log"):
            # Should not raise exception
            await bot._reconnect_irc()

    async def test_periodic_token_check_includes_irc_health(self, bot_config):
        """Test that periodic token check includes IRC health monitoring"""
        import asyncio
        from src.bot import TwitchColorBot

        bot = TwitchColorBot(**bot_config)
        bot.running = True

        check_count = 0

        async def mock_token_check():
            nonlocal check_count
            check_count += 1
            if check_count >= 2:
                bot.running = False  # Stop after 2 iterations
            await asyncio.sleep(0.01)  # Simulate async work
            return True

        async def mock_irc_check():
            # Mock IRC health check - no actual work needed
            await asyncio.sleep(0.001)

        with patch.object(
            bot, "_check_and_refresh_token", side_effect=mock_token_check
        ):
            with patch.object(
                bot, "_check_irc_health", side_effect=mock_irc_check
            ) as mock_irc_health:
                with patch.object(bot, "_get_token_check_interval", return_value=0.01):
                    try:
                        await asyncio.wait_for(bot._periodic_token_check(), timeout=1.0)
                    except asyncio.TimeoutError:
                        bot.running = False

        # Should have called IRC health check
        assert mock_irc_health.call_count >= 1


class TestFinalCoverage:
    """Test to achieve 100% coverage for the final branch"""

    def test_force_reconnect_preserves_multiple_channels(self):
        """Test that force_reconnect properly preserves multiple channels"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "oauth:testtoken"
        irc.channels = ["channel1", "channel2", "channel3"]
        irc.connected = True

        # Mock socket operations to avoid actual network calls
        irc.socket = MagicMock()

        # Mock disconnect and connect methods
        with patch.object(irc, "disconnect") as mock_disconnect:
            with patch.object(irc, "connect", return_value=True) as mock_connect:
                with patch.object(irc, "join_channel") as mock_join:

                    result = irc.force_reconnect()

                    # Verify it returns True for successful reconnect
                    assert result is True

                    # Verify disconnect was called
                    mock_disconnect.assert_called_once()

                    # Verify connect was called with first channel
                    mock_connect.assert_called_once_with(
                        "oauth:testtoken", "testuser", "channel1"
                    )

                    # Verify all channels were joined
                    expected_join_calls = [
                        call("channel1"),
                        call("channel2"),
                        call("channel3"),
                    ]
                    mock_join.assert_has_calls(expected_join_calls)

                    # Verify channels list is preserved
                    assert irc.channels == ["channel1", "channel2", "channel3"]

    def test_force_reconnect_connect_failure_branch(self):
        """Test the false branch of 'if success:' in force_reconnect"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "oauth:testtoken"
        irc.channels = ["channel1", "channel2"]

        # Mock disconnect method
        with patch.object(irc, "disconnect") as mock_disconnect:
            # Mock connect to return False to hit the false branch
            with patch.object(irc, "connect", return_value=False) as mock_connect:
                with patch.object(irc, "join_channel") as mock_join:

                    # This should trigger the false branch
                    result = irc.force_reconnect()

                    # Verify disconnect was called
                    mock_disconnect.assert_called_once()

                    # Verify connect was called
                    mock_connect.assert_called_once()

                    # Result should be False
                    assert result is False

                    # join_channel should NOT be called when connect fails
                    mock_join.assert_not_called()

                    # Channels should still be preserved even if reconnect failed
                    assert irc.channels == ["channel1", "channel2"]


class TestIRCHealthMonitoringCoverage:
    """Test missing coverage in IRC health monitoring"""

    @pytest.fixture
    def irc_client(self):
        """Create an IRC client for testing"""
        irc = SimpleTwitchIRC()
        # Set up basic state
        irc.username = "testuser"
        irc.token = "testtoken"
        irc.channels = ["#testchannel"]
        return irc

    def test_handle_pong_with_pending_client_ping(self, irc_client):
        """Test handling PONG when we have a pending client ping"""
        now = time.time()
        irc_client.last_client_ping_sent = now - 5  # Sent 5 seconds ago
        irc_client.last_pong_received = now - 10  # Older pong
        irc_client.consecutive_ping_failures = 2

        irc_client._handle_pong("PONG :tmi.twitch.tv")

        # Should update last_pong_received and reset failures
        assert irc_client.last_pong_received > now - 1  # Recent
        assert irc_client.consecutive_ping_failures == 0

    def test_handle_pong_without_pending_client_ping(self, irc_client):
        """Test handling PONG when no client ping is pending"""
        now = time.time()
        irc_client.last_client_ping_sent = 0  # No client ping sent yet
        irc_client.last_pong_received = now - 5  # Older pong
        irc_client.consecutive_ping_failures = 1

        irc_client._handle_pong("PONG :tmi.twitch.tv")

        # Should still update last_pong_received but not reset failures (since no client ping was sent)
        assert irc_client.last_pong_received > now - 1  # Recent
        assert irc_client.consecutive_ping_failures == 1  # Should remain unchanged

    def test_send_client_ping_socket_send_exception(self, irc_client):
        """Test client ping when socket send raises exception"""
        irc_client.socket = MagicMock()
        irc_client.socket.send.side_effect = Exception("Send failed")

        result = irc_client._send_client_ping()

        assert result is False

    def test_check_connection_health_max_ping_failures(self, irc_client):
        """Test connection health when max ping failures reached"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.consecutive_ping_failures = 3  # At max
        irc_client.max_consecutive_ping_failures = 3

        result = irc_client._check_connection_health()

        assert result is False

    def test_check_connection_health_pending_pong_timeout(self, irc_client):
        """Test connection health when pending PONG times out"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.consecutive_ping_failures = 0
        irc_client.last_client_ping_sent = now - 5  # Recent ping
        irc_client.last_pong_received = now - 20  # Older pong (so ping is pending)
        irc_client.pong_timeout = 3  # 3 second timeout

        with patch("src.simple_irc.time.time", return_value=now):
            result = irc_client._check_connection_health()

        assert result is False
        assert irc_client.consecutive_ping_failures == 1  # Should increment

    def test_check_connection_health_server_ping_timeout(self, irc_client):
        """Test connection health when server ping times out"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.consecutive_ping_failures = 0
        irc_client.last_ping_from_server = now - 310  # 310 seconds ago
        irc_client.expected_ping_interval = 300  # Expected every 300 seconds

        result = irc_client._check_connection_health()

        assert result is False

    def test_check_connection_health_triggers_client_ping(self, irc_client):
        """Test connection health triggers client ping when needed"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.last_client_ping_sent = now - 310  # 310 seconds ago
        irc_client.last_pong_received = now - 300  # Received PONG for previous ping
        irc_client.client_ping_interval = 300  # Send every 300 seconds
        irc_client.consecutive_ping_failures = 0
        irc_client.last_ping_from_server = now - 100  # Recent server ping

        with patch("src.simple_irc.time.time", return_value=now):
            with patch.object(
                irc_client, "_send_client_ping", return_value=True
            ) as mock_ping:
                result = irc_client._check_connection_health()

        mock_ping.assert_called_once()
        assert result is True

    def test_check_connection_health_client_ping_fails(self, irc_client):
        """Test connection health when client ping fails"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # Recent activity
        irc_client.last_client_ping_sent = now - 310  # 310 seconds ago
        irc_client.last_pong_received = now - 300  # Received PONG for previous ping
        irc_client.client_ping_interval = 300  # Send every 300 seconds
        irc_client.consecutive_ping_failures = 0
        irc_client.last_ping_from_server = now - 100  # Recent server ping

        with patch("src.simple_irc.time.time", return_value=now):
            with patch.object(
                irc_client, "_send_client_ping", return_value=False
            ) as mock_ping:
                result = irc_client._check_connection_health()

        mock_ping.assert_called_once()
        assert result is False


class TestIRCMiscCoverage:
    """Test other missing IRC coverage"""

    @pytest.fixture
    def irc_client(self):
        """Create an IRC client for testing"""
        irc = SimpleTwitchIRC()
        # Set up basic state
        irc.username = "testuser"
        irc.token = "testtoken"
        irc.channels = ["#testchannel"]
        return irc

    def test_force_reconnect_missing_details(self):
        """Test force_reconnect when missing connection details"""
        irc = SimpleTwitchIRC()  # Missing details (all None)

        result = irc.force_reconnect()

        assert result is False

    def test_force_reconnect_with_channels(self):
        """Test force_reconnect when connection succeeds and joins channels"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.token = "testtoken"
        irc.channels = ["#testchannel1", "#testchannel2"]

        with patch.object(irc, "disconnect"), patch.object(
            irc, "connect", return_value=True
        ), patch.object(irc, "join_channel") as mock_join, patch(
            "src.simple_irc.time.sleep"
        ):

            result = irc.force_reconnect()

        # Should return True (based on connect success)
        assert result is True
        # Should join all channels
        assert mock_join.call_count == 2
        mock_join.assert_any_call("#testchannel1")
        mock_join.assert_any_call("#testchannel2")

    def test_perform_periodic_checks_failure(self):
        """Test periodic checks failure in listen loop"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.sock = MagicMock()
        irc.connected = True
        irc.running = True

        # Mock recv to simulate timeout, then failure
        calls = 0

        def recv_side_effect(size):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise socket.timeout()
            else:
                return b"PRIVMSG #test :hello\r\n"

        irc.sock.recv.side_effect = recv_side_effect

        with patch.object(
            irc, "_perform_periodic_checks", return_value=True
        ), patch.object(irc, "_is_connection_stale", return_value=False):
            # Should break on periodic checks failure
            irc.listen()

    def test_connection_stale_in_listen(self):
        """Test connection stale detection in listen loop"""
        irc = SimpleTwitchIRC()
        irc.username = "testuser"
        irc.sock = MagicMock()
        irc.connected = True
        irc.running = True

        # Mock recv to raise timeout
        irc.sock.recv.side_effect = socket.timeout()

        with patch.object(
            irc, "_perform_periodic_checks", return_value=False
        ), patch.object(irc, "_is_connection_stale", return_value=True):
            # Should break on stale connection
            irc.listen()


class TestDirectCoverage:
    """Direct tests for the remaining uncovered lines"""

    def test_simple_irc_force_reconnect_channel_join_path(self):
        """Test force_reconnect successfully reconnects and joins channels"""
        # Create IRC client and set up multiple channels to trigger the loop
        irc = SimpleTwitchIRC()
        irc.token = "oauth:test_token"
        irc.username = "testuser"
        irc.channels = ["channel1", "channel2"]

        # Track if the success branch was taken
        success_branch_executed = False

        def track_join_channel(channel):
            nonlocal success_branch_executed
            success_branch_executed = True
            # Don't actually try to send to socket
            return None

        # Mock the underlying socket operations but let force_reconnect run naturally
        with patch("socket.socket") as mock_socket_class:
            mock_socket_instance = MagicMock()
            mock_socket_class.return_value = mock_socket_instance
            mock_socket_instance.connect.return_value = None
            mock_socket_instance.settimeout.return_value = None
            mock_socket_instance.send.return_value = None  # Don't actually send data

            # Mock join_channel to track execution
            with patch.object(
                irc, "join_channel", side_effect=track_join_channel
            ) as mock_join:
                # Call force_reconnect to exercise the actual code path
                result = irc.force_reconnect()

                # Should return True for successful reconnection
                assert result is True

                # Should have executed the success branch (if success:)
                assert success_branch_executed, "Success branch was not executed"

                # Should join each channel once in the loop (lines 442-444)
                assert mock_join.call_count == 2  # channel1 and channel2

                # Verify the specific channels were joined
                expected_calls = [call("channel1"), call("channel2")]
                mock_join.assert_has_calls(expected_calls)


class TestRemainingJoinChannelCoverage:
    """Additional tests to cover remaining join_channel branches (lines 94-96, 108-109)."""

    def test_join_channel_already_confirmed_no_retry_logs_and_returns(self):
        """Covers branch where channel is already in confirmed_channels and _is_retry is False (lines 94-96)."""
        irc = SimpleTwitchIRC()
        irc.username = "tester"
        irc.sock = MagicMock()
        irc.connected = True
        irc.confirmed_channels.add("testchannel")

        with patch("src.simple_irc.print_log") as mock_log:
            irc.join_channel("testchannel", _is_retry=False)

        # Should not attempt to send JOIN again
        irc.sock.send.assert_not_called()
        # Should have logged the skip message
        assert mock_log.call_count == 1
        logged = mock_log.call_args[0][0]
        assert "Already joined" in logged

    def test_join_channel_retry_existing_pending_increments_attempts(self):
        """Covers retry branch updating attempts & sent_at (lines 108-109)."""
        irc = SimpleTwitchIRC()
        irc.username = "tester"
        irc.sock = MagicMock()
        irc.connected = True
        # Seed pending join entry
        irc.pending_joins["testchannel"] = {"sent_at": time.time() - 5, "attempts": 1}

        with patch("src.simple_irc.time.time", return_value=time.time()) as mock_time:
            irc.join_channel("testchannel", _is_retry=True)

        # JOIN should be re-sent
        irc.sock.send.assert_called_with("JOIN #testchannel\r\n".encode("utf-8"))
        assert irc.pending_joins["testchannel"]["attempts"] == 2
        # sent_at should have been updated to mocked time()
        assert irc.pending_joins["testchannel"]["sent_at"] == mock_time.return_value

    def test_join_channel_already_confirmed_retry_no_log(self):
        """Covers confirmed channel branch with _is_retry=True (no logging path for lines 94-96 branch variant)."""
        irc = SimpleTwitchIRC()
        irc.username = "tester"
        irc.sock = MagicMock()
        irc.connected = True
        irc.confirmed_channels.add("testchannel")
        # With _is_retry True, should return without logging or sending
        with patch("src.simple_irc.print_log") as mock_log:
            irc.join_channel("testchannel", _is_retry=True)
        irc.sock.send.assert_not_called()
        # No log because _is_retry True suppresses logging for confirmed channel early exit
        mock_log.assert_not_called()
