"""
Unit tests for ConfigValidator.
"""

from unittest.mock import Mock, patch

from src.config.config_validator import ConfigValidator


class TestConfigValidator:
    """Test class for ConfigValidator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        pass

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_validate_and_filter_users_filters_invalid_types(self):
        """Test validate_and_filter_users filters out non-dict items."""
        raw_users = [
            {"username": "user1", "color": "#FF0000"},
            "not_a_dict",
            {"username": "user2", "color": "#00FF00"},
            123
        ]

        with patch('src.config.config_validator.UserConfig.from_dict') as mock_from_dict:
            mock_uc1 = Mock()
            mock_uc1.validate.return_value = True
            mock_uc1.username = "user1"
            mock_uc1.to_dict.return_value = {"username": "user1", "color": "#FF0000"}

            mock_uc2 = Mock()
            mock_uc2.validate.return_value = True
            mock_uc2.username = "user2"
            mock_uc2.to_dict.return_value = {"username": "user2", "color": "#00FF00"}

            mock_from_dict.side_effect = [mock_uc1, mock_uc2]

            result = ConfigValidator.validate_and_filter_users(raw_users)

        assert len(result) == 2
        assert result[0]["username"] == "user1"
        assert result[1]["username"] == "user2"

    def test_validate_and_filter_users_filters_invalid_users(self):
        """Test validate_and_filter_users filters out users that fail validation."""
        raw_users = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"},
            {"username": "", "color": "#0000FF"}  # Invalid: empty username
        ]

        with patch('src.config.config_validator.UserConfig.from_dict') as mock_from_dict:
            mock_uc1 = Mock()
            mock_uc1.validate.return_value = True
            mock_uc1.username = "user1"
            mock_uc1.to_dict.return_value = {"username": "user1", "color": "#FF0000"}

            mock_uc2 = Mock()
            mock_uc2.validate.return_value = True
            mock_uc2.username = "user2"
            mock_uc2.to_dict.return_value = {"username": "user2", "color": "#00FF00"}

            mock_uc3 = Mock()
            mock_uc3.validate.return_value = False  # Fails validation

            mock_from_dict.side_effect = [mock_uc1, mock_uc2, mock_uc3]

            result = ConfigValidator.validate_and_filter_users(raw_users)

        assert len(result) == 2
        assert all(u["username"] in ["user1", "user2"] for u in result)

    def test_validate_and_filter_users_removes_duplicates(self):
        """Test validate_and_filter_users removes duplicate usernames."""
        raw_users = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "USER1", "color": "#00FF00"},  # Duplicate (case insensitive)
            {"username": "user2", "color": "#0000FF"}
        ]

        with patch('src.config.config_validator.UserConfig.from_dict') as mock_from_dict:
            mock_uc1 = Mock()
            mock_uc1.validate.return_value = True
            mock_uc1.username = "user1"
            mock_uc1.to_dict.return_value = {"username": "user1", "color": "#FF0000"}

            mock_uc2 = Mock()
            mock_uc2.validate.return_value = True
            mock_uc2.username = "USER1"
            mock_uc2.to_dict.return_value = {"username": "USER1", "color": "#00FF00"}

            mock_uc3 = Mock()
            mock_uc3.validate.return_value = True
            mock_uc3.username = "user2"
            mock_uc3.to_dict.return_value = {"username": "user2", "color": "#0000FF"}

            mock_from_dict.side_effect = [mock_uc1, mock_uc2, mock_uc3]

            result = ConfigValidator.validate_and_filter_users(raw_users)

        # Should only keep first occurrence of user1
        assert len(result) == 2
        usernames = [u["username"] for u in result]
        assert "user1" in usernames
        assert "user2" in usernames
        assert "USER1" not in usernames

    def test_validate_and_filter_users_handles_validation_errors(self):
        """Test validate_and_filter_users handles ValidationError exceptions."""
        raw_users = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "invalid_user"},  # Will cause ValidationError
            {"username": "user2", "color": "#00FF00"}
        ]

        with patch('src.config.config_validator.UserConfig.from_dict') as mock_from_dict:
            mock_uc1 = Mock()
            mock_uc1.validate.return_value = True
            mock_uc1.username = "user1"
            mock_uc1.to_dict.return_value = {"username": "user1", "color": "#FF0000"}

            mock_uc3 = Mock()
            mock_uc3.validate.return_value = True
            mock_uc3.username = "user2"
            mock_uc3.to_dict.return_value = {"username": "user2", "color": "#00FF00"}

            mock_from_dict.side_effect = [mock_uc1, Exception("Validation error"), mock_uc3]

            result = ConfigValidator.validate_and_filter_users(raw_users)

        assert len(result) == 2
        assert result[0]["username"] == "user1"
        assert result[1]["username"] == "user2"

    def test_validate_and_filter_users_to_dataclasses(self):
        """Test validate_and_filter_users_to_dataclasses returns UserConfig instances."""
        raw_users = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"}
        ]

        with patch('src.config.config_validator.UserConfig.from_dict') as mock_from_dict:
            mock_uc1 = Mock()
            mock_uc1.validate.return_value = True
            mock_uc1.username = "user1"

            mock_uc2 = Mock()
            mock_uc2.validate.return_value = True
            mock_uc2.username = "user2"

            mock_from_dict.side_effect = [mock_uc1, mock_uc2]

            result = ConfigValidator.validate_and_filter_users_to_dataclasses(raw_users)

        assert len(result) == 2
        assert result[0] == mock_uc1
        assert result[1] == mock_uc2
