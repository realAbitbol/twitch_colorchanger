"""
Unit tests for ConfigSaver.
"""

from unittest.mock import Mock, patch

from src.config.config_saver import ConfigSaver


class TestConfigSaver:
    """Test class for ConfigSaver functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.saver = ConfigSaver()

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_with_dependencies(self):
        """Test ConfigSaver initialization with custom dependencies."""
        mock_loader = Mock()
        mock_validator = Mock()
        saver = ConfigSaver(loader=mock_loader, validator=mock_validator)
        assert saver.loader == mock_loader
        assert saver.validator == mock_validator

    def test_init_without_dependencies(self):
        """Test ConfigSaver initialization without dependencies creates defaults."""
        saver = ConfigSaver()
        assert saver.loader is not None
        assert saver.validator is not None

    def test_save_users_to_config(self):
        """Test save_users_to_config saves users through repository."""
        mock_users = [{"username": "testuser"}]
        mock_repo = Mock()

        with patch('src.config.config_saver.normalize_user_list', return_value=(mock_users, False)) as mock_normalize, \
             patch('src.config.config_saver.ConfigRepository', return_value=mock_repo) as mock_repo_class:
            mock_repo.save_users.return_value = True

            self.saver.save_users_to_config(mock_users, "test.conf")

        mock_normalize.assert_called_once_with(mock_users)
        mock_repo_class.assert_called_once_with("test.conf")
        mock_repo.save_users.assert_called_once_with(mock_users)
        mock_repo.verify_readback.assert_called_once()

    def test_save_users_to_config_retry_on_failure(self):
        """Test save_users_to_config retries when initial save fails."""
        mock_users = [{"username": "testuser"}]
        mock_repo = Mock()

        with patch('src.config.config_saver.normalize_user_list', return_value=(mock_users, True)), \
             patch('src.config.config_saver.ConfigRepository', return_value=mock_repo):
            mock_repo.save_users.return_value = False

            self.saver.save_users_to_config(mock_users, "test.conf")

        # Should call save_users twice: once initially, once on retry
        assert mock_repo.save_users.call_count == 2
        assert mock_repo.verify_readback.call_count == 1

    def test_update_user_in_config_success(self):
        """Test update_user_in_config succeeds with valid user."""
        user_dict = {
            "username": "testuser",
            "color": "#FF0000",
            "token": "token123",
            "enabled": True
        }

        mock_uc = Mock()
        mock_uc.normalize.return_value = False
        mock_uc.validate.return_value = True
        mock_uc.to_dict.return_value = user_dict

        with patch('src.config.config_saver.UserConfig.from_dict', return_value=mock_uc), \
             patch.object(self.saver.loader, 'load_users_from_config', return_value=[]), \
             patch.object(self.saver, '_merge_user', return_value=([], False)), \
             patch.object(self.saver, 'save_users_to_config') as mock_save:
            result = self.saver.update_user_in_config(user_dict, "test.conf")

        assert result is True
        mock_save.assert_called_once_with([user_dict], "test.conf")

    def test_update_user_in_config_invalid_user(self):
        """Test update_user_in_config fails with invalid user."""
        user_dict = {"username": "testuser"}

        mock_uc = Mock()
        mock_uc.validate.return_value = False

        with patch('src.config.config_saver.UserConfig.from_dict', return_value=mock_uc), \
             patch('src.config.config_saver.logging') as mock_logging:
            result = self.saver.update_user_in_config(user_dict, "test.conf")

        assert result is False
        mock_logging.warning.assert_called_once()

    def test_update_user_in_config_handles_exceptions(self):
        """Test update_user_in_config handles exceptions gracefully."""
        user_dict = {"username": "testuser"}

        with patch('src.config.config_saver.UserConfig.from_dict', side_effect=ValueError("Invalid")), \
             patch('src.config.config_saver.logging') as mock_logging:
            result = self.saver.update_user_in_config(user_dict, "test.conf")

        assert result is False
        mock_logging.error.assert_called_once()

    def test_merge_user_replaces_existing(self):
        """Test _merge_user replaces existing user with same username."""
        existing_users = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "testuser", "color": "#00FF00"}
        ]

        mock_uc = Mock()
        mock_uc.username = "testuser"
        mock_uc.to_dict.return_value = {"username": "testuser", "color": "#0000FF", "token": "newtoken"}

        users, replaced = self.saver._merge_user(existing_users, mock_uc)

        assert replaced is True
        assert len(users) == 2
        # Check that testuser was updated
        testuser_entry = next(u for u in users if u.get("username") == "testuser")
        assert testuser_entry["color"] == "#0000FF"
        assert testuser_entry["token"] == "newtoken"

    def test_merge_user_adds_new(self):
        """Test _merge_user does not add new user when username not found."""
        existing_users = [{"username": "user1", "color": "#FF0000"}]

        mock_uc = Mock()
        mock_uc.username = "newuser"
        mock_uc.to_dict.return_value = {"username": "newuser", "color": "#00FF00"}

        users, replaced = self.saver._merge_user(existing_users, mock_uc)

        assert replaced is False
        assert len(users) == 1
        assert not any(u.get("username") == "newuser" for u in users)

    def test_log_update_invalid(self):
        """Test _log_update_invalid logs warning and returns False."""
        mock_uc = Mock()
        mock_uc.username = "testuser"

        with patch('src.config.config_saver.logging') as mock_logging:
            result = self.saver._log_update_invalid(mock_uc)

        assert result is False
        mock_logging.warning.assert_called_once()

    def test_log_update_normalized(self):
        """Test _log_update_normalized logs info message."""
        mock_uc = Mock()
        mock_uc.username = "testuser"
        mock_uc.channels = ["channel1", "channel2"]

        with patch('src.config.config_saver.logging') as mock_logging:
            self.saver._log_update_normalized(mock_uc)

        mock_logging.info.assert_called_once()

    def test_log_update_failed(self):
        """Test _log_update_failed logs error message."""
        user_dict = {"username": "testuser"}
        exception = ValueError("Test error")

        with patch('src.config.config_saver.logging') as mock_logging:
            self.saver._log_update_failed(exception, user_dict)

        mock_logging.error.assert_called_once()
