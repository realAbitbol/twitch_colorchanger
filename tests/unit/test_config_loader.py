"""
Unit tests for ConfigLoader.
"""

import pytest
from unittest.mock import Mock, patch

from src.config.config_loader import ConfigLoader
from src.config.repository import ConfigRepository


class TestConfigLoader:
    """Test class for ConfigLoader functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.loader = ConfigLoader()

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_with_validator(self):
        """Test ConfigLoader initialization with custom validator."""
        mock_validator = Mock()
        loader = ConfigLoader(validator=mock_validator)
        assert loader.validator == mock_validator

    def test_init_without_validator(self):
        """Test ConfigLoader initialization without validator creates default."""
        loader = ConfigLoader()
        assert loader.validator is not None

    def test_load_users_from_config(self):
        """Test load_users_from_config loads users from repository."""
        mock_repo = Mock()
        mock_repo.load_raw.return_value = [{"username": "testuser"}]

        with patch('src.config.config_loader.ConfigRepository', return_value=mock_repo):
            result = self.loader.load_users_from_config("test.conf")

        assert result == [{"username": "testuser"}]
        mock_repo.load_raw.assert_called_once()

    @patch.dict('os.environ', {'TWITCH_CONF_FILE': 'custom.conf'})
    def test_get_configuration_uses_env_config_file(self):
        """Test get_configuration uses TWITCH_CONF_FILE environment variable."""
        mock_users = [{"username": "testuser", "color": "#FF0000", "token": "token123", "enabled": True}]

        with patch.object(self.loader, 'load_users_from_config', return_value=mock_users) as mock_load:
            with patch.object(self.loader.validator, 'validate_and_filter_users_to_dataclasses', return_value=[Mock()]) as mock_validate:
                with patch('src.config.config_loader.logging') as mock_logging:
                    result = self.loader.get_configuration()

        mock_load.assert_called_once_with('custom.conf')
        assert result is not None

    def test_get_configuration_uses_default_config_file(self):
        """Test get_configuration uses default config file when no env var."""
        mock_users = [{"username": "testuser", "color": "#FF0000", "token": "token123", "enabled": True}]

        with patch.object(self.loader, 'load_users_from_config', return_value=mock_users) as mock_load:
            with patch.object(self.loader.validator, 'validate_and_filter_users_to_dataclasses', return_value=[Mock()]) as mock_validate:
                with patch('src.config.config_loader.logging') as mock_logging:
                    result = self.loader.get_configuration()

        mock_load.assert_called_once_with('twitch_colorchanger.conf')
        assert result is not None

    def test_get_configuration_exits_when_no_config_file(self):
        """Test get_configuration exits when no config file found."""
        with patch('os.environ', {"TWITCH_CONF_FILE": "nonexistent.conf"}):
            with patch.object(ConfigRepository, 'load_raw', return_value=[]):
                with patch('src.config.config_loader.logging') as mock_logging:
                    with pytest.raises(SystemExit):
                        self.loader.get_configuration()

        mock_logging.error.assert_called()

    def test_get_configuration_exits_when_no_valid_users(self):
        """Test get_configuration exits when no valid users found."""
        mock_users = [{"username": "testuser"}]

        with patch.object(self.loader, 'load_users_from_config', return_value=mock_users):
            with patch.object(self.loader.validator, 'validate_and_filter_users_to_dataclasses', return_value=[]):
                with patch('src.config.config_loader.logging') as mock_logging:
                    with patch('sys.exit') as mock_exit:
                        self.loader.get_configuration()

        mock_logging.error.assert_called()
        mock_exit.assert_called_once_with(1)

    def test_get_configuration_success(self):
        """Test get_configuration succeeds with valid users."""
        mock_users = [{"username": "testuser", "color": "#FF0000", "token": "token123", "enabled": True}]
        mock_validated_users = [Mock()]

        with patch.object(self.loader, 'load_users_from_config', return_value=mock_users):
            with patch.object(self.loader.validator, 'validate_and_filter_users_to_dataclasses', return_value=mock_validated_users):
                with patch('src.config.config_loader.logging') as mock_logging:
                    result = self.loader.get_configuration()

        assert result == mock_validated_users
        mock_logging.info.assert_called_once()