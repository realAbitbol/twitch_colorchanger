"""
Unit tests for ConnectionCoordinator.
"""

from pathlib import Path
from unittest.mock import Mock, patch

from src.chat.connection_coordinator import ConnectionCoordinator


class TestConnectionCoordinator:
    """Test class for ConnectionCoordinator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_backend = Mock()
        self.coordinator = ConnectionCoordinator(self.mock_backend)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_calls_initialize_components(self):
        """Test that __init__ calls _initialize_components."""
        with patch.object(ConnectionCoordinator, '_initialize_components') as mock_init:
            ConnectionCoordinator(self.mock_backend)
            mock_init.assert_called_once()

    def test_initialize_components_creates_cache_manager_when_none(self):
        """Test _initialize_components creates CacheManager when backend has none."""
        # Arrange
        self.mock_backend._cache_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._msg_processor = None
        self.mock_backend._api = Mock()

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._cache_manager is not None
        assert self.mock_backend._channel_resolver is not None
        assert self.mock_backend._msg_processor is not None

    @patch('src.chat.connection_coordinator.os.getenv', return_value='/custom/cache.json')
    def test_initialize_components_uses_env_cache_path(self, mock_getenv):
        """Test _initialize_components uses TWITCH_BROADCASTER_CACHE env var."""
        # Arrange
        self.mock_backend._cache_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._msg_processor = None
        self.mock_backend._api = Mock()

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._cache_manager is not None
        # Verify the cache path was set correctly
        assert self.mock_backend._cache_manager._cache_file_path == '/custom/cache.json'

    def test_initialize_components_uses_default_cache_path(self):
        """Test _initialize_components uses default cache path when no env var."""
        # Arrange
        self.mock_backend._cache_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._msg_processor = None
        self.mock_backend._api = Mock()

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._cache_manager is not None
        expected_path = Path("broadcaster_ids.cache.json").resolve()
        assert self.mock_backend._cache_manager._cache_file_path == str(expected_path)

    def test_initialize_components_skips_existing_components(self):
        """Test _initialize_components skips components that already exist."""
        # Arrange
        mock_cache = Mock()
        mock_resolver = Mock()
        mock_processor = Mock()
        self.mock_backend._cache_manager = mock_cache
        self.mock_backend._channel_resolver = mock_resolver
        self.mock_backend._msg_processor = mock_processor

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._cache_manager is mock_cache
        assert self.mock_backend._channel_resolver is mock_resolver
        assert self.mock_backend._msg_processor is mock_processor

    def test_initialize_components_creates_message_processor_with_handlers(self):
        """Test _initialize_components creates MessageProcessor with correct handlers."""
        # Arrange
        self.mock_backend._cache_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._msg_processor = None
        self.mock_backend._api = Mock()
        mock_message_handler = Mock()
        mock_color_handler = Mock()
        self.mock_backend._message_handler = mock_message_handler
        self.mock_backend._color_handler = mock_color_handler

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._msg_processor is not None
        # Verify MessageProcessor was created with correct handlers
        assert self.mock_backend._msg_processor.message_handler == mock_message_handler
        assert self.mock_backend._msg_processor.color_handler == mock_color_handler

    def test_initialize_components_creates_message_processor_with_default_handlers(self):
        """Test _initialize_components creates MessageProcessor with default handlers when None."""
        # Arrange
        self.mock_backend._cache_manager = None
        self.mock_backend._channel_resolver = None
        self.mock_backend._msg_processor = None
        self.mock_backend._api = Mock()
        self.mock_backend._message_handler = None
        self.mock_backend._color_handler = None

        # Act
        self.coordinator._initialize_components()

        # Assert
        assert self.mock_backend._msg_processor is not None
        # Verify MessageProcessor was created with lambda handlers
        assert callable(self.mock_backend._msg_processor.message_handler)
        assert callable(self.mock_backend._msg_processor.color_handler)

    def test_initialize_credential_components_creates_token_manager(self):
        """Test initialize_credential_components creates TokenManager when conditions met."""
        # Arrange
        self.mock_backend._token_manager = None
        self.mock_backend._ws_manager = None
        self.mock_backend._session = Mock()
        self.mock_backend._on_token_invalid = Mock()

        # Act
        self.coordinator.initialize_credential_components(
            token="test_token",
            client_id="test_client_id",
            client_secret="test_client_secret",
            username="test_user"
        )

        # Assert
        assert self.mock_backend._token_manager is not None
        assert self.mock_backend._ws_manager is not None

    def test_initialize_credential_components_skips_token_manager_when_missing_credentials(self):
        """Test initialize_credential_components skips TokenManager when client_id or secret missing."""
        # Arrange
        self.mock_backend._token_manager = None
        self.mock_backend._ws_manager = None
        self.mock_backend._session = Mock()

        # Act - missing client_secret
        self.coordinator.initialize_credential_components(
            token="test_token",
            client_id="test_client_id",
            client_secret=None,
            username="test_user"
        )

        # Assert
        assert self.mock_backend._token_manager is None

    def test_initialize_credential_components_skips_ws_manager_when_missing_credentials(self):
        """Test initialize_credential_components skips WSManager when token or client_id missing."""
        # Arrange
        self.mock_backend._token_manager = None
        self.mock_backend._ws_manager = None
        self.mock_backend._session = Mock()

        # Act - missing token
        self.coordinator.initialize_credential_components(
            token=None,
            client_id="test_client_id",
            client_secret="test_client_secret",
            username="test_user"
        )

        # Assert
        assert self.mock_backend._ws_manager is None

    def test_initialize_credential_components_skips_existing_components(self):
        """Test initialize_credential_components skips components that already exist."""
        # Arrange
        mock_token_manager = Mock()
        mock_ws_manager = Mock()
        self.mock_backend._token_manager = mock_token_manager
        self.mock_backend._ws_manager = mock_ws_manager

        # Act
        self.coordinator.initialize_credential_components(
            token="test_token",
            client_id="test_client_id",
            client_secret="test_client_secret",
            username="test_user"
        )

        # Assert
        assert self.mock_backend._token_manager is mock_token_manager
        assert self.mock_backend._ws_manager is mock_ws_manager
