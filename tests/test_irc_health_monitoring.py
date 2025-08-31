"""
Tests for IRC connection health monitoring functionality
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from src.simple_irc import SimpleTwitchIRC
from src.bot import TwitchColorBot


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
            'token': 'test_token',
            'refresh_token': 'test_refresh_token',
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'nick': 'testuser',
            'channels': ['testchannel'],
            'is_prime_or_turbo': True,
            'config_file': None,
            'user_id': None
        }

    def test_health_monitoring_initialization(self, irc_client):
        """Test health monitoring fields are initialized"""
        assert irc_client.last_ping_sent == 0
        assert irc_client.last_pong_received == 0
        assert irc_client.last_server_activity == 0
        assert irc_client.ping_interval == 60
        assert irc_client.pong_timeout == 15
        assert irc_client.health_check_interval == 300
        assert irc_client.last_health_check == 0
        assert irc_client.connection_failures == 0
        assert irc_client.max_connection_failures == 3

    def test_handle_pong(self, irc_client):
        """Test PONG message handling"""
        test_time = time.time()
        
        with patch('src.simple_irc.time.time', return_value=test_time):
            with patch('src.simple_irc.print_log'):
                irc_client._handle_pong("PONG :tmi.twitch.tv")
        
        assert irc_client.last_pong_received == test_time
        assert irc_client.last_server_activity == test_time

    def test_send_ping_success(self, irc_client):
        """Test successful PING sending"""
        mock_socket = MagicMock()
        irc_client.sock = mock_socket
        irc_client.connected = True
        
        test_time = time.time()
        with patch('src.simple_irc.time.time', return_value=test_time):
            with patch('src.simple_irc.print_log'):
                result = irc_client._send_ping()
        
        assert result is True
        assert irc_client.last_ping_sent == test_time
        mock_socket.send.assert_called_once()

    def test_send_ping_failure(self, irc_client):
        """Test PING sending failure"""
        mock_socket = MagicMock()
        mock_socket.send.side_effect = Exception("Send failed")
        irc_client.sock = mock_socket
        irc_client.connected = True
        
        with patch('src.simple_irc.print_log'):
            result = irc_client._send_ping()
        
        assert result is False

    def test_send_ping_not_connected(self, irc_client):
        """Test PING sending when not connected"""
        result = irc_client._send_ping()
        assert result is False

    def test_check_connection_health_healthy(self, irc_client):
        """Test connection health check when healthy"""
        now = time.time()
        irc_client.last_server_activity = now - 30  # 30 seconds ago
        irc_client.last_pong_received = now
        irc_client.last_ping_sent = now - 10
        
        with patch('src.simple_irc.time.time', return_value=now):
            result = irc_client._check_connection_health()
        
        assert result is True
        assert irc_client.last_health_check == now

    def test_check_connection_health_pong_timeout(self, irc_client):
        """Test connection health check with PONG timeout"""
        now = time.time()
        irc_client.last_ping_sent = now - 20  # 20 seconds ago
        irc_client.last_pong_received = now - 30  # 30 seconds ago
        irc_client.pong_timeout = 15  # Expect PONG within 15 seconds
        
        with patch('src.simple_irc.time.time', return_value=now):
            with patch('src.simple_irc.print_log'):
                result = irc_client._check_connection_health()
        
        assert result is False

    def test_check_connection_health_send_ping(self, irc_client):
        """Test connection health check sends PING when needed"""
        now = time.time()
        irc_client.last_server_activity = now - 70  # 70 seconds ago (> ping_interval)
        irc_client.last_pong_received = now
        irc_client.last_ping_sent = now - 70
        
        with patch('src.simple_irc.time.time', return_value=now):
            with patch.object(irc_client, '_send_ping', return_value=True) as mock_send_ping:
                result = irc_client._check_connection_health()
        
        mock_send_ping.assert_called_once()
        assert result is True

    def test_is_connection_stale_activity_timeout(self, irc_client):
        """Test stale connection detection by activity timeout"""
        now = time.time()
        irc_client.last_server_activity = now - 130  # > ping_interval * 2
        irc_client.ping_interval = 60
        
        with patch('src.simple_irc.time.time', return_value=now):
            result = irc_client._is_connection_stale()
        
        assert result is True

    def test_is_connection_stale_pong_timeout(self, irc_client):
        """Test stale connection detection by PONG timeout"""
        now = time.time()
        irc_client.last_ping_sent = now - 20
        irc_client.last_pong_received = now - 30
        irc_client.pong_timeout = 15
        
        with patch('src.simple_irc.time.time', return_value=now):
            result = irc_client._is_connection_stale()
        
        assert result is True

    def test_is_connection_stale_healthy(self, irc_client):
        """Test stale connection detection when healthy"""
        now = time.time()
        irc_client.last_server_activity = now - 30
        irc_client.last_ping_sent = now - 10
        irc_client.last_pong_received = now - 5
        
        with patch('src.simple_irc.time.time', return_value=now):
            result = irc_client._is_connection_stale()
        
        assert result is False

    def test_process_line_updates_activity(self, irc_client):
        """Test that processing lines updates server activity"""
        test_time = time.time()
        
        with patch('src.simple_irc.time.time', return_value=test_time):
            with patch.object(irc_client, '_parse_message', return_value=None):
                irc_client._process_line("SOME IRC LINE")
        
        assert irc_client.last_server_activity == test_time

    def test_process_line_handles_pong(self, irc_client):
        """Test that PONG messages are handled"""
        with patch.object(irc_client, '_handle_pong') as mock_handle_pong:
            irc_client._process_line("PONG :tmi.twitch.tv")
        
        mock_handle_pong.assert_called_once_with("PONG :tmi.twitch.tv")

    def test_perform_periodic_checks_health_failure(self, irc_client):
        """Test periodic checks when health check fails"""
        irc_client.connection_failures = 2
        irc_client.max_connection_failures = 3
        
        with patch.object(irc_client, '_check_join_timeouts'):
            with patch.object(irc_client, '_check_connection_health', return_value=False):
                with patch('src.simple_irc.print_log'):
                    result = irc_client._perform_periodic_checks()
        
        assert result is True  # Should trigger disconnection
        assert irc_client.connection_failures == 3

    def test_perform_periodic_checks_health_success(self, irc_client):
        """Test periodic checks when health check succeeds"""
        irc_client.connection_failures = 1
        
        with patch.object(irc_client, '_check_join_timeouts'):
            with patch.object(irc_client, '_check_connection_health', return_value=True):
                result = irc_client._perform_periodic_checks()
        
        assert result is False  # Should continue
        assert irc_client.connection_failures == 0  # Reset on success

    def test_listen_initializes_health_monitoring(self, irc_client):
        """Test that listen() initializes health monitoring timestamps"""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""  # Empty data to break loop
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True
        
        test_time = time.time()
        with patch('src.simple_irc.time.time', return_value=test_time):
            with patch('src.simple_irc.print_log'):
                irc_client.listen()
        
        assert irc_client.last_server_activity == test_time
        assert irc_client.last_pong_received == test_time
        assert irc_client.last_health_check == test_time

    def test_listen_detects_stale_connection_on_timeout(self, irc_client):
        """Test that listen() detects stale connections on socket timeout"""
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [Exception("timeout"), b""]  # Timeout then empty
        irc_client.sock = mock_socket
        irc_client.running = True
        irc_client.connected = True
        
        with patch.object(irc_client, '_is_connection_stale', return_value=True):
            with patch('src.simple_irc.print_log'):
                irc_client.listen()

    def test_is_healthy(self, irc_client):
        """Test is_healthy() method"""
        # Not connected
        assert irc_client.is_healthy() is False
        
        # Connected but stale
        irc_client.connected = True
        irc_client.sock = MagicMock()
        with patch.object(irc_client, '_is_connection_stale', return_value=True):
            assert irc_client.is_healthy() is False
        
        # Connected and healthy
        with patch.object(irc_client, '_is_connection_stale', return_value=False):
            assert irc_client.is_healthy() is True

    def test_get_connection_stats(self, irc_client):
        """Test get_connection_stats() method"""
        now = time.time()
        irc_client.connected = True
        irc_client.running = True
        irc_client.last_server_activity = now - 30
        irc_client.connection_failures = 2
        
        with patch('src.simple_irc.time.time', return_value=now):
            with patch.object(irc_client, 'is_healthy', return_value=True):
                stats = irc_client.get_connection_stats()
        
        assert stats['connected'] is True
        assert stats['running'] is True
        assert stats['last_server_activity'] == now - 30
        assert stats['time_since_activity'] == 30
        assert stats['connection_failures'] == 2
        assert stats['is_healthy'] is True

    def test_force_reconnect_success(self, irc_client):
        """Test successful force reconnection"""
        irc_client.username = "testuser"
        irc_client.token = "oauth:token"
        irc_client.channels = ["testchannel"]
        
        with patch.object(irc_client, 'disconnect'):
            with patch.object(irc_client, 'connect', return_value=True) as mock_connect:
                with patch('src.simple_irc.time.sleep'):
                    with patch('src.simple_irc.print_log'):
                        result = irc_client.force_reconnect()
        
        assert result is True
        mock_connect.assert_called_once_with("oauth:token", "testuser", "testchannel")

    def test_force_reconnect_missing_details(self, irc_client):
        """Test force reconnection with missing connection details"""
        with patch('src.simple_irc.print_log'):
            result = irc_client.force_reconnect()
        
        assert result is False


class TestBotIRCHealthIntegration:
    """Test bot IRC health monitoring integration"""

    @pytest.fixture
    def bot_config(self):
        """Bot configuration for testing"""
        return {
            'token': 'test_token',
            'refresh_token': 'test_refresh_token',
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'nick': 'testuser',
            'channels': ['testchannel'],
            'is_prime_or_turbo': True,
            'config_file': None,
            'user_id': None
        }

    async def test_check_irc_health_healthy(self, bot_config):
        """Test IRC health check when connection is healthy"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.return_value = {
            'is_healthy': True,
            'time_since_activity': 30.0,
            'connection_failures': 0
        }
        bot.irc = mock_irc
        
        with patch('src.bot.print_log'):
            await bot._check_irc_health()
        
        mock_irc.get_connection_stats.assert_called_once()

    async def test_check_irc_health_unhealthy(self, bot_config):
        """Test IRC health check when connection is unhealthy"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.return_value = {
            'is_healthy': False,
            'time_since_activity': 150.0,
            'connection_failures': 2
        }
        bot.irc = mock_irc
        
        with patch.object(bot, '_reconnect_irc') as mock_reconnect:
            with patch('src.bot.print_log'):
                await bot._check_irc_health()
        
        mock_reconnect.assert_called_once()

    async def test_check_irc_health_no_irc(self, bot_config):
        """Test IRC health check when no IRC connection exists"""
        bot = TwitchColorBot(**bot_config)
        bot.irc = None
        
        # Should not raise exception
        await bot._check_irc_health()

    async def test_check_irc_health_exception(self, bot_config):
        """Test IRC health check with exception"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.get_connection_stats.side_effect = Exception("Stats error")
        bot.irc = mock_irc
        
        with patch('src.bot.print_log'):
            # Should not raise exception
            await bot._check_irc_health()

    async def test_reconnect_irc_success(self, bot_config):
        """Test successful IRC reconnection"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.return_value = True
        bot.irc = mock_irc
        
        mock_task = MagicMock()
        mock_task.done.return_value = False
        bot.irc_task = mock_task
        
        with patch('src.bot.asyncio.get_event_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop
            
            with patch('src.bot.print_log'):
                with patch('src.bot.asyncio.wait_for'):
                    await bot._reconnect_irc()
        
        mock_irc.force_reconnect.assert_called_once()
        mock_loop.run_in_executor.assert_called_once()

    async def test_reconnect_irc_failure(self, bot_config):
        """Test failed IRC reconnection"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.return_value = False
        bot.irc = mock_irc
        bot.irc_task = None
        
        with patch('src.bot.print_log'):
            await bot._reconnect_irc()
        
        mock_irc.force_reconnect.assert_called_once()

    async def test_reconnect_irc_exception(self, bot_config):
        """Test IRC reconnection with exception"""
        bot = TwitchColorBot(**bot_config)
        mock_irc = MagicMock()
        mock_irc.force_reconnect.side_effect = Exception("Reconnect error")
        bot.irc = mock_irc
        
        with patch('src.bot.print_log'):
            # Should not raise exception
            await bot._reconnect_irc()

    async def test_periodic_token_check_includes_irc_health(self, bot_config):
        """Test that periodic token check includes IRC health monitoring"""
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
        
        with patch.object(bot, '_check_and_refresh_token', side_effect=mock_token_check):
            with patch.object(bot, '_check_irc_health', side_effect=mock_irc_check) as mock_irc_health:
                with patch.object(bot, '_get_token_check_interval', return_value=0.01):
                    try:
                        await asyncio.wait_for(bot._periodic_token_check(), timeout=1.0)
                    except asyncio.TimeoutError:
                        bot.running = False
        
        # Should have called IRC health check
        assert mock_irc_health.call_count >= 1
