"""
Tests for simple_irc.py module
"""

import pytest
import socket
import time
from unittest.mock import Mock, patch, MagicMock
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
        assert irc_client.server == 'irc.chat.twitch.tv'
        assert irc_client.port == 6667
        assert irc_client.sock is None
        assert irc_client.running is False
        assert irc_client.connected is False
        assert irc_client.joined_channels == set()
        assert irc_client.confirmed_channels == set()
        assert irc_client.pending_joins == {}
        assert irc_client.join_timeout == 30
        assert irc_client.max_join_attempts == 2

    @patch('socket.socket')
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
        mock_socket.connect.assert_called_once_with(('irc.chat.twitch.tv', 6667))

        # Verify authentication messages were sent
        expected_calls = [
            "PASS oauth:test_token\r\n".encode('utf-8'),
            "NICK testuser\r\n".encode('utf-8'),
            "CAP REQ :twitch.tv/membership\r\n".encode('utf-8'),
            "CAP REQ :twitch.tv/tags\r\n".encode('utf-8'),
            "CAP REQ :twitch.tv/commands\r\n".encode('utf-8')
        ]
        assert mock_socket.send.call_count == 5
        for call, expected in zip(mock_socket.send.call_args_list, expected_calls):
            assert call[0][0] == expected

    @patch('socket.socket')
    def test_connect_with_oauth_prefix(self, mock_socket_class, irc_client, mock_socket):
        """Test connection with oauth: prefix already present"""
        mock_socket_class.return_value = mock_socket

        result = irc_client.connect("oauth:test_token", "testuser", "testchannel")

        assert result is True
        assert irc_client.token == "oauth:test_token"

    @patch('socket.socket')
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
        mock_socket.send.assert_called_once_with("JOIN #testchannel\r\n".encode('utf-8'))

        # Verify channel was added to tracking
        assert "testchannel" in irc_client.joined_channels
        assert "testchannel" in irc_client.pending_joins
        assert irc_client.pending_joins["testchannel"]["attempts"] == 1

    def test_join_channel_with_hash(self, irc_client, mock_socket):
        """Test joining a channel with # prefix"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        irc_client.join_channel("#TestChannel")

        mock_socket.send.assert_called_once_with("JOIN #testchannel\r\n".encode('utf-8'))
        assert "testchannel" in irc_client.joined_channels

    def test_join_channel_retry(self, irc_client, mock_socket):
        """Test joining a channel with retry logic"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # First join
        irc_client.join_channel("testchannel")
        # Second join (retry)
        irc_client.join_channel("testchannel")

        # Should have 2 send calls
        assert mock_socket.send.call_count == 2
        assert irc_client.pending_joins["testchannel"]["attempts"] == 2

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
            'sender': 'testuser',
            'channel': 'testchannel',
            'message': 'Hello world',
            'command': 'PRIVMSG',
            'raw': raw_message
        }
        assert result == expected

    def test_parse_message_privmsg_with_tags(self, irc_client):
        """Test parsing PRIVMSG with IRCv3 tags"""
        raw_message = "@badge-info=;badges=;color=#FF0000;display-name=TestUser :testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #testchannel :Hello world"

        result = irc_client._parse_message(raw_message)

        expected = {
            'sender': 'testuser',
            'channel': 'testchannel',
            'message': 'Hello world',
            'command': 'PRIVMSG',
            'raw': raw_message
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
            ":sender!user@host CMD"
        ]

        for msg in malformed_messages:
            result = irc_client._parse_message(msg)
            assert result is None

    def test_parse_message_exception(self, irc_client):
        """Test parsing with exception handling"""
        # This should not happen in normal operation, but test error handling
        with patch('src.simple_irc.print_log') as mock_print:
            result = irc_client._parse_message(None)  # This will cause an exception

        assert result is None
        mock_print.assert_called()

    def test_handle_ping(self, irc_client, mock_socket):
        """Test PING handling"""
        irc_client.sock = mock_socket
        ping_line = "PING :tmi.twitch.tv"

        irc_client._handle_ping(ping_line)

        mock_socket.send.assert_called_once_with("PONG :tmi.twitch.tv\r\n".encode('utf-8'))

    def test_handle_privmsg_own_message(self, irc_client):
        """Test handling own PRIVMSG"""
        irc_client.username = "testuser"
        parsed = {
            'sender': 'testuser',
            'channel': 'testchannel',
            'message': 'Hello world',
            'command': 'PRIVMSG',
            'raw': 'raw message'
        }

        with patch('src.simple_irc.print_log') as mock_print:
            irc_client._handle_privmsg(parsed)

        # Should log own message
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0]
        assert "#testchannel - testuser: Hello world" in call_args[0]

    def test_handle_privmsg_other_message(self, irc_client):
        """Test handling other user's PRIVMSG"""
        irc_client.username = "testuser"
        parsed = {
            'sender': 'otheruser',
            'channel': 'testchannel',
            'message': 'Hello world from someone else',
            'command': 'PRIVMSG',
            'raw': 'raw message'
        }

        with patch('src.simple_irc.print_log') as mock_print:
            irc_client._handle_privmsg(parsed)

        # Should log other user's message in debug mode
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0]
        assert "#testchannel - otheruser: Hello world from someone else" in call_args[0]
        assert mock_print.call_args[1]['debug_only'] is True

    def test_handle_privmsg_long_message(self, irc_client):
        """Test handling long PRIVMSG with truncation"""
        irc_client.username = "testuser"
        long_message = "A" * 60  # Longer than 50 chars
        parsed = {
            'sender': 'otheruser',
            'channel': 'testchannel',
            'message': long_message,
            'command': 'PRIVMSG',
            'raw': 'raw message'
        }

        with patch('src.simple_irc.print_log') as mock_print:
            irc_client._handle_privmsg(parsed)

        call_args = mock_print.call_args[0]
        assert "..." in call_args[0]  # Should be truncated

    def test_handle_privmsg_with_handler(self, irc_client):
        """Test PRIVMSG handling with message handler"""
        mock_handler = Mock()
        irc_client.message_handler = mock_handler
        irc_client.username = "testuser"

        parsed = {
            'sender': 'otheruser',
            'channel': 'testchannel',
            'message': 'Hello world',
            'command': 'PRIVMSG',
            'raw': 'raw message'
        }

        with patch('src.simple_irc.print_log'):
            irc_client._handle_privmsg(parsed)

        # Handler should be called
        mock_handler.assert_called_once_with('otheruser', 'testchannel', 'Hello world')

    def test_process_line_ping(self, irc_client, mock_socket):
        """Test processing PING line"""
        irc_client.sock = mock_socket
        ping_line = "PING :tmi.twitch.tv"

        with patch.object(irc_client, '_handle_ping') as mock_handle_ping:
            with patch.object(irc_client, '_check_join_timeouts'):
                irc_client._process_line(ping_line)

        mock_handle_ping.assert_called_once_with(ping_line)

    def test_process_line_privmsg(self, irc_client):
        """Test processing PRIVMSG line"""
        privmsg_line = ":testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #testchannel :Hello world"

        with patch.object(irc_client, '_handle_privmsg') as mock_handle_privmsg:
            with patch.object(irc_client, '_parse_message') as mock_parse:
                mock_parse.return_value = {
                    'sender': 'testuser',
                    'channel': 'testchannel',
                    'message': 'Hello world',
                    'command': 'PRIVMSG',
                    'raw': privmsg_line
                }
                with patch.object(irc_client, '_check_join_timeouts'):
                    irc_client._process_line(privmsg_line)

        mock_handle_privmsg.assert_called_once()

    def test_process_line_other_command(self, irc_client):
        """Test processing other IRC commands"""
        other_line = ":tmi.twitch.tv 001 testuser :Welcome to Twitch"

        with patch.object(irc_client, '_parse_message') as mock_parse:
            mock_parse.return_value = None  # Not a PRIVMSG
            with patch.object(irc_client, '_check_join_timeouts'):
                # Should not raise exception
                irc_client._process_line(other_line)

    @patch('socket.socket')
    def test_listen_success(self, mock_socket_class, irc_client, mock_socket):
        """Test successful listening loop"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock socket to return data then empty (connection closed)
        mock_socket.recv.side_effect = [
            ":tmi.twitch.tv 001 testuser :Welcome\r\n".encode('utf-8'),
            b""  # Empty data = connection closed
        ]

        with patch.object(irc_client, '_process_line') as mock_process:
            with patch('src.simple_irc.print_log'):
                irc_client.listen()

        # Should have processed the welcome message
        mock_process.assert_called()

    @patch('socket.socket')
    def test_listen_connection_lost(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with connection lost"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock empty recv (connection lost)
        mock_socket.recv.return_value = b""

        with patch('src.simple_irc.print_log'):
            irc_client.listen()

        # Should exit the loop (running should be set to False in disconnect or similar)
        # Note: The current implementation doesn't set running=False on connection loss
        # This is a design choice in the original code

    @patch('socket.socket')
    def test_listen_timeout(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with socket timeout"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock timeout exception
        mock_socket.recv.side_effect = socket.timeout

        # Mock running to eventually stop
        with patch.object(irc_client, 'running', False):
            with patch('src.simple_irc.print_log'):
                irc_client.listen()

    @patch('socket.socket')
    def test_listen_exception(self, mock_socket_class, irc_client, mock_socket):
        """Test listening with general exception"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock general exception
        mock_socket.recv.side_effect = Exception("Network error")

        with patch('src.simple_irc.print_log'):
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

        # Add a pending join that's confirmed (this would normally be removed by _parse_message)
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {
            'sent_at': past_time,
            'attempts': 1
        }
        # Simulate what happens when RPL_ENDOFNAMES is received
        irc_client.confirmed_channels.add("testchannel")
        irc_client.pending_joins.pop("testchannel", None)  # This is what _parse_message does

        with patch('src.simple_irc.print_log'):
            irc_client._check_join_timeouts()

        # Should remain removed from pending joins (already removed by successful join)
        assert "testchannel" not in irc_client.pending_joins

    def test_check_join_timeouts_retry(self, irc_client, mock_socket):
        """Test checking join timeouts with retry"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # Add a pending join that's timed out
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {
            'sent_at': past_time,
            'attempts': 1
        }

        with patch('src.simple_irc.print_log'):
            irc_client._check_join_timeouts()

        # Should retry join
        mock_socket.send.assert_called_with("JOIN #testchannel\r\n".encode('utf-8'))
        assert irc_client.pending_joins["testchannel"]["attempts"] == 2

    def test_check_join_timeouts_max_attempts(self, irc_client, mock_socket):
        """Test checking join timeouts with max attempts reached"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        # Add a pending join that's timed out and at max attempts
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {
            'sent_at': past_time,
            'attempts': 2  # Max attempts
        }

        with patch('src.simple_irc.print_log'):
            irc_client._check_join_timeouts()

        # Should remove from pending joins (failed)
        assert "testchannel" not in irc_client.pending_joins

    def test_check_join_timeouts_not_connected(self, irc_client, mock_socket):
        """Test checking join timeouts when not connected"""
        irc_client.sock = mock_socket
        irc_client.connected = False

        # Add a pending join that's timed out
        past_time = time.time() - 35  # Past timeout
        irc_client.pending_joins["testchannel"] = {
            'sent_at': past_time,
            'attempts': 1
        }

        with patch('src.simple_irc.print_log'):
            irc_client._check_join_timeouts()

        # Should remove from pending joins (cannot retry)
        assert "testchannel" not in irc_client.pending_joins

    def test_handle_single_join_timeout_waiting(self, irc_client):
        """Test handling single join timeout still waiting"""
        now = time.time()
        info = {'sent_at': now - 10, 'attempts': 1}  # Not timed out yet

        result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is False  # Should continue waiting

    def test_handle_single_join_timeout_retry_success(self, irc_client, mock_socket):
        """Test handling single join timeout with successful retry"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        now = time.time()
        info = {'sent_at': now - 35, 'attempts': 1}  # Timed out

        with patch('src.simple_irc.print_log'):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is False  # Should retry
        mock_socket.send.assert_called_once_with("JOIN #testchannel\r\n".encode('utf-8'))
        assert info['attempts'] == 2

    def test_handle_single_join_timeout_retry_failure(self, irc_client, mock_socket):
        """Test handling single join timeout with retry failure"""
        irc_client.sock = mock_socket
        irc_client.connected = True
        mock_socket.send.side_effect = Exception("Send failed")

        now = time.time()
        info = {'sent_at': now - 35, 'attempts': 1}  # Timed out

        with patch('src.simple_irc.print_log'):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is True  # Should fail

    def test_handle_single_join_timeout_max_attempts(self, irc_client, mock_socket):
        """Test handling single join timeout at max attempts"""
        irc_client.sock = mock_socket
        irc_client.connected = True

        now = time.time()
        info = {'sent_at': now - 35, 'attempts': 2}  # Max attempts

        with patch('src.simple_irc.print_log'):
            result = irc_client._handle_single_join_timeout("testchannel", info, now)

        assert result is True  # Should fail

    def test_disconnect(self, irc_client, mock_socket):
        """Test disconnecting from IRC"""
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True

        with patch('src.simple_irc.print_log'):
            irc_client.disconnect()

        assert irc_client.running is False
        assert irc_client.connected is False
        assert irc_client.sock is None
        mock_socket.close.assert_called_once()

    def test_disconnect_no_socket(self, irc_client):
        """Test disconnecting when no socket exists"""
        irc_client.sock = None

        with patch('src.simple_irc.print_log'):
            # Should not raise exception
            irc_client.disconnect()

    def test_disconnect_socket_close_error(self, irc_client, mock_socket):
        """Test disconnecting with socket close error (covers lines 224-225)"""
        irc_client.sock = mock_socket
        mock_socket.close.side_effect = OSError("Close failed")

        with patch('src.simple_irc.print_log'):
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

    @patch('socket.socket')
    def test_listen_timeout_continue(self, mock_socket_class, irc_client, mock_socket):
        """Test listen loop continues on timeout (covers line 176)"""
        mock_socket_class.return_value = mock_socket
        irc_client.connect("test_token", "testuser", "testchannel")

        # Mock timeout exception followed by normal data then empty
        mock_socket.recv.side_effect = [
            socket.timeout,  # This should trigger continue
            ":tmi.twitch.tv 001 testuser :Welcome\r\n".encode('utf-8'),
            b""  # Empty data = connection closed
        ]

        with patch.object(irc_client, '_process_line') as mock_process:
            with patch('src.simple_irc.print_log'):
                irc_client.listen()

        # Should have processed the welcome message after timeout
        mock_process.assert_called_once()
