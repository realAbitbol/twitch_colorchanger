"""
Unit tests for ConnectionStateManager.
"""

import time
from unittest.mock import Mock, patch

from src.chat.connection_state_manager import ConnectionState, ConnectionStateManager


class TestConnectionStateManager:
    """Test class for ConnectionStateManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.connector = Mock()
        self.manager = ConnectionStateManager(self.connector)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_sets_initial_state(self):
        """Test ConnectionStateManager initialization sets correct initial state."""
        assert self.manager.connection_state == ConnectionState.DISCONNECTED
        assert self.manager.session_id is None
        assert self.manager.pending_reconnect_session_id is None
        assert self.manager.pending_challenge is None
        assert self.manager.last_sequence is None
        assert isinstance(self.manager.last_activity, float)

    def test_is_connected_returns_true_when_connected(self):
        """Test is_connected returns True when WebSocket is connected."""
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws

        assert self.manager.is_connected is True

    def test_is_connected_returns_false_when_no_websocket(self):
        """Test is_connected returns False when no WebSocket."""
        self.connector.ws = None

        assert self.manager.is_connected is False

    def test_is_connected_returns_false_when_websocket_closed(self):
        """Test is_connected returns False when WebSocket is closed."""
        mock_ws = Mock()
        mock_ws.closed = True
        self.connector.ws = mock_ws

        assert self.manager.is_connected is False

    def test_is_healthy_returns_false_when_not_connected(self):
        """Test is_healthy returns False when not connected."""
        self.connector.ws = None

        assert self.manager.is_healthy() is False

    def test_is_healthy_returns_false_when_not_connected_state(self):
        """Test is_healthy returns False when connection state is not CONNECTED."""
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTING

        assert self.manager.is_healthy() is False

    def test_is_healthy_returns_false_when_no_session_id(self):
        """Test is_healthy returns False when no session_id."""
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTED
        self.manager.session_id = None

        assert self.manager.is_healthy() is False

    def test_is_healthy_returns_true_when_healthy(self):
        """Test is_healthy returns True when all conditions are met."""
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTED
        self.manager.session_id = "session123"
        self.manager.last_activity = time.monotonic()  # Recent activity

        assert self.manager.is_healthy() is True

    def test_is_healthy_detects_stale_connection(self):
        """Test is_healthy returns False for stale connections (>60s inactivity)."""
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTED
        self.manager.session_id = "session123"
        self.manager.last_activity = time.monotonic() - 120  # 2 minutes ago

        # The method returns False for stale connections
        assert self.manager.is_healthy() is False

    @patch('time.monotonic')
    def test_is_healthy_returns_true_at_exactly_60_seconds(self, mock_monotonic):
        """Test is_healthy returns True at exactly 60 seconds (boundary case)."""
        mock_monotonic.return_value = 100.0
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTED
        self.manager.session_id = "session123"
        self.manager.last_activity = 100.0 - 60.0  # Exactly 60 seconds ago

        assert self.manager.is_healthy() is True

    @patch('time.monotonic')
    def test_is_healthy_returns_false_slightly_over_60_seconds(self, mock_monotonic):
        """Test is_healthy returns False slightly over 60 seconds."""
        mock_monotonic.return_value = 100.0
        mock_ws = Mock()
        mock_ws.closed = False
        self.connector.ws = mock_ws
        self.manager.connection_state = ConnectionState.CONNECTED
        self.manager.session_id = "session123"
        self.manager.last_activity = 100.0 - 61.0  # 61 seconds ago

        assert self.manager.is_healthy() is False

    def test_update_url_updates_connector_url(self):
        """Test update_url updates the connector's WebSocket URL."""
        new_url = "wss://new.url.com"
        self.connector.ws_url = "wss://old.url.com"

        self.manager.update_url(new_url)

        assert self.connector.ws_url == new_url

    def test_update_url_skips_same_url(self):
        """Test update_url does nothing when URL is the same."""
        same_url = "wss://same.url.com"
        self.connector.ws_url = same_url

        self.manager.update_url(same_url)

        assert self.connector.ws_url == same_url

    def test_update_url_skips_empty_url(self):
        """Test update_url does nothing when new URL is empty."""
        old_url = "wss://old.url.com"
        self.connector.ws_url = old_url

        self.manager.update_url("")

        assert self.connector.ws_url == old_url
