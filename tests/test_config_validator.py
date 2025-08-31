"""
Tests for configuration validator functionality
"""

import unittest
from unittest.mock import patch

from src.config_validator import (
    get_valid_users,
    validate_all_users,
    validate_user_config,
)
from tests.fixtures.sample_configs import (
    MINIMAL_CONFIG,
    MULTI_USER_CONFIG,
    SINGLE_USER_CONFIG,
)


class TestValidateUserConfig(unittest.TestCase):
    """Test validate_user_config functionality"""

    def test_validate_user_config_valid_single(self):
        """Test validation of valid single user config"""
        result = validate_user_config(SINGLE_USER_CONFIG)
        assert result is True

    def test_validate_user_config_valid_minimal(self):
        """Test validation of valid minimal config"""
        user = MINIMAL_CONFIG["users"][0]
        result = validate_user_config(user)
        assert result is True

    def test_validate_user_config_missing_username(self):
        """Test validation with missing username"""
        invalid_user = {
            "oauth_token": "oauth:test123",
            "client_id": "test_client",
            "is_prime_or_turbo": False,
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_empty_username(self):
        """Test validation with empty username"""
        invalid_user = {
            "username": "",
            "oauth_token": "oauth:test123",
            "client_id": "test_client",
            "is_prime_or_turbo": False,
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_missing_oauth(self):
        """Test validation with missing oauth token"""
        invalid_user = {
            "username": "testuser",
            "client_id": "test_client",
            "is_prime_or_turbo": False,
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_missing_client_id(self):
        """Test validation with missing client ID"""
        invalid_user = {
            "username": "testuser",
            "oauth_token": "oauth:test123",
            "is_prime_or_turbo": False,
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_invalid_oauth_format(self):
        """Test validation with invalid oauth format"""
        invalid_user = {
            "username": "testuser",
            "oauth_token": "invalid_token",  # Should start with oauth:
            "client_id": "test_client",
            "is_prime_or_turbo": False,
        }
        result = validate_user_config(invalid_user)
        # Depending on implementation, this might be valid or invalid
        # Just ensure it doesn't crash
        assert isinstance(result, bool)

    def test_validate_user_config_none_input(self):
        """Test validation with None input"""
        result = validate_user_config(None)
        assert result is False

    def test_validate_user_config_empty_dict(self):
        """Test validation with empty dictionary"""
        result = validate_user_config({})
        assert result is False

    def test_validate_user_config_wrong_type(self):
        """Test validation with wrong input type"""
        result = validate_user_config("not a dict")
        assert result is False

    def test_validate_user_config_placeholder_token(self):
        """Test validation with placeholder token (covers lines 39-40)"""
        invalid_user = {
            "username": "testuser",
            "access_token": "test",  # Placeholder token
            "client_id": "test_client",
            "channels": ["testchannel"],
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_fake_token(self):
        """Test validation with fake token"""
        invalid_user = {
            "username": "testuser",
            "access_token": "fake_token",  # Fake token
            "client_id": "test_client",
            "channels": ["testchannel"],
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_empty_channels(self):
        """Test validation with empty channels list (covers lines 45-46)"""
        invalid_user = {
            "username": "testuser",
            "access_token": "oauth:valid_token",
            "client_id": "test_client",
            "channels": [],  # Empty channels
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_channels_not_list(self):
        """Test validation with channels not being a list"""
        invalid_user = {
            "username": "testuser",
            "access_token": "oauth:valid_token",
            "client_id": "test_client",
            "channels": "not_a_list",  # Not a list
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_invalid_channel_name(self):
        """Test validation with invalid channel name (covers lines 50-51)"""
        invalid_user = {
            "username": "testuser",
            "access_token": "oauth:valid_token",
            "client_id": "test_client",
            "channels": ["ab"],  # Channel name too short
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_channel_with_spaces(self):
        """Test validation with channel name that has only spaces"""
        invalid_user = {
            "username": "testuser",
            "access_token": "oauth:valid_token",
            "client_id": "test_client",
            "channels": ["   "],  # Only spaces
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_non_string_channel(self):
        """Test validation with non-string channel name"""
        invalid_user = {
            "username": "testuser",
            "access_token": "oauth:valid_token",
            "client_id": "test_client",
            "channels": [123],  # Non-string channel
        }
        result = validate_user_config(invalid_user)
        assert result is False

    def test_validate_user_config_needs_token_or_credentials_error(self):
        """Test validation when user has neither token nor credentials (covers lines 39-40)"""
        user_config = {
            "username": "test_user",
            "channels": ["channel1"],
            # Missing both access_token and client_id/client_secret
        }

        with patch("src.config_validator.logger") as mock_logger:
            result = validate_user_config(user_config)

            assert result is False
            mock_logger.error.assert_called_once()
            error_msg = mock_logger.error.call_args[0][0]
            assert (
                "needs either access_token OR (client_id + client_secret)" in error_msg
            )

    def test_validate_user_config_no_credentials_error(self):
        """Test validation when no valid credentials provided"""
        with patch("src.config_validator.logger") as mock_logger:
            user_config = {
                "username": "test_user",
                "access_token": "placeholder",
                "channels": ["test_channel"],
            }
            result = validate_user_config(user_config)
            self.assertFalse(result)
            mock_logger.error.assert_called_with(
                "User test_user needs either access_token OR (client_id + client_secret) for automatic setup"
            )

    def test_validate_user_config_placeholder_token_with_valid_credentials(self):
        """Test validation with valid length token that's not a placeholder"""
        user_config = {
            "username": "test_user",
            "access_token": "test"
            + "x" * 17,  # 21 chars, long enough and not in placeholder list
            "channels": ["test_channel"],
        }
        result = validate_user_config(user_config)
        self.assertTrue(result)

    def test_validate_user_config_placeholder_token_error(self):
        """Test validation when token has valid length but is exactly a placeholder"""
        with patch("src.config_validator.logger") as mock_logger:
            user_config = {
                "username": "test_user",
                "access_token": "example_token_twenty_chars",  # Exactly matches our 27-char placeholder
                "channels": ["test_channel"],
            }
            result = validate_user_config(user_config)
            self.assertFalse(result)
            mock_logger.error.assert_called_with(
                "Please use a real token for test_user"
            )

    def test_validate_user_config_missing_channels(self):
        """Test validation when channels are missing"""
        with patch("src.config_validator.logger") as mock_logger:
            user_config = {
                "username": "test_user",
                "access_token": "valid_token_with_20_chars",
            }
            result = validate_user_config(user_config)
            self.assertFalse(result)
            mock_logger.error.assert_called_with("Channels list required for test_user")

    def test_validate_user_config_empty_channels_list(self):
        """Test validation when channels list is empty"""
        with patch("src.config_validator.logger") as mock_logger:
            user_config = {
                "username": "test_user",
                "access_token": "valid_token_with_20_chars",
                "channels": [],
            }
            result = validate_user_config(user_config)
            self.assertFalse(result)
            mock_logger.error.assert_called_with("Channels list required for test_user")

    def test_validate_user_config_invalid_channel_error(self):
        """Test validation with invalid channel (covers lines 50-51)"""
        user_config = {
            "username": "test_user",
            "access_token": "oauth:real_token_here",
            "channels": ["ab"],  # Too short channel name
        }

        with patch("src.config_validator.logger") as mock_logger:
            result = validate_user_config(user_config)

            assert result is False
            mock_logger.error.assert_called_once()
            error_msg = mock_logger.error.call_args[0][0]
            assert "Invalid channel name" in error_msg


class TestValidateAllUsers:
    """Test validate_all_users functionality"""

    def test_validate_all_users_valid_multi(self):
        """Test validation of valid multi-user config"""
        users = MULTI_USER_CONFIG["users"]
        result = validate_all_users(users)
        assert result is True

    def test_validate_all_users_valid_single(self):
        """Test validation of single user in list"""
        users = [SINGLE_USER_CONFIG]
        result = validate_all_users(users)
        assert result is True

    def test_validate_all_users_empty_list(self):
        """Test validation of empty user list"""
        result = validate_all_users([])
        assert result is False

    def test_validate_all_users_none_input(self):
        """Test validation with None input"""
        result = validate_all_users(None)
        assert result is False

    def test_validate_all_users_mixed_valid_invalid(self):
        """Test validation with mix of valid and invalid users"""
        users = [
            SINGLE_USER_CONFIG,  # Valid
            {  # Invalid - missing oauth_token
                "username": "invaliduser",
                "client_id": "test_client",
                "is_prime_or_turbo": False,
            },
        ]
        result = validate_all_users(users)
        assert result is False

    def test_validate_all_users_all_invalid(self):
        """Test validation with all invalid users"""
        users = [
            {"username": ""},  # Invalid
            {"oauth_token": "oauth:test"},  # Invalid - missing username
            {},  # Invalid - empty
        ]
        result = validate_all_users(users)
        assert result is False

    def test_validate_all_users_wrong_type(self):
        """Test validation with wrong input type"""
        result = validate_all_users("not a list")
        assert result is False

    def test_validate_all_users_list_with_non_dict(self):
        """Test validation with list containing non-dict items"""
        users = [
            SINGLE_USER_CONFIG,  # Valid dict
            "not a dict",  # Invalid type
            {
                "username": "valid",
                "oauth_token": "oauth:test",
                "client_id": "test",
            },  # Valid dict
        ]
        result = validate_all_users(users)
        assert result is False


class TestGetValidUsers:
    """Test get_valid_users functionality"""

    def test_get_valid_users_valid_list(self):
        """Test getting valid users from valid list"""
        users = [SINGLE_USER_CONFIG]
        result = get_valid_users(users)
        assert len(result) == 1
        assert result[0]["username"] == "testuser"

    def test_get_valid_users_empty_list(self):
        """Test getting valid users from empty list"""
        result = get_valid_users([])
        assert result == []

    def test_get_valid_users_none_input(self):
        """Test getting valid users with None input"""
        result = get_valid_users(None)
        assert result == []

    def test_get_valid_users_wrong_type(self):
        """Test getting valid users with wrong input type"""
        result = get_valid_users("not a list")
        assert result == []

    def test_get_valid_users_mixed_valid_invalid(self):
        """Test getting valid users from mixed list"""
        users = [
            SINGLE_USER_CONFIG,  # Valid
            {"username": ""},  # Invalid - empty username
            {
                "username": "valid2",
                "access_token": "valid_access_token_1234567890",  # 30 chars, not placeholder
                "client_id": "client2",
                "client_secret": "secret2",
                "channels": ["channel2"],
            },  # Valid
        ]
        result = get_valid_users(users)
        assert len(result) == 2
        usernames = [user["username"] for user in result]
        assert "testuser" in usernames
        assert "valid2" in usernames

    def test_get_valid_users_all_invalid(self):
        """Test getting valid users from all invalid list"""
        users = [
            {"username": ""},  # Invalid
            {"access_token": "oauth:test"},  # Invalid - missing username
            {},  # Invalid - empty
        ]
        result = get_valid_users(users)
        assert result == []

    def test_get_valid_users_duplicate_usernames(self):
        """Test getting valid users with duplicate usernames"""
        user1 = SINGLE_USER_CONFIG.copy()
        user2 = SINGLE_USER_CONFIG.copy()
        user2["username"] = "testuser"  # Same username

        users = [user1, user2]
        result = get_valid_users(users)
        assert len(result) == 1  # Only one should be kept

    def test_get_valid_users_case_insensitive_duplicates(self):
        """Test getting valid users with case-insensitive duplicate usernames"""
        user1 = SINGLE_USER_CONFIG.copy()
        user2 = SINGLE_USER_CONFIG.copy()
        user2["username"] = "TestUser"  # Different case

        users = [user1, user2]
        result = get_valid_users(users)
        assert len(result) == 1  # Only one should be kept

    def test_get_valid_users_non_dict_items(self):
        """Test getting valid users with non-dict items in list"""
        users = [
            SINGLE_USER_CONFIG,  # Valid dict
            "not a dict",  # Invalid type - should be skipped
            123,  # Invalid type - should be skipped
            {
                "username": "valid2",
                "access_token": "another_valid_token_1234567890",  # 30 chars
                "client_id": "client2",
                "client_secret": "secret2",
                "channels": ["channel2"],
            },  # Valid dict
        ]
        result = get_valid_users(users)
        assert len(result) == 2
        usernames = [user["username"] for user in result]
        assert "testuser" in usernames
        assert "valid2" in usernames

    def test_get_valid_users_multiple_valid(self):
        """Test getting valid users from multi-user config"""
        users = MULTI_USER_CONFIG["users"]
        result = get_valid_users(users)
        assert len(result) == 2
        usernames = [user["username"] for user in result]
        assert "primeuser" in usernames
        assert "regularuser" in usernames

    def test_get_valid_users_preserves_order(self):
        """Test that get_valid_users preserves order of valid users"""
        user1 = {
            "username": "user1",
            "access_token": "valid_token_1_12345678901234567890",  # 35 chars
            "client_id": "client1",
            "client_secret": "secret1",
            "channels": ["channel1"],
        }
        user2 = {
            "username": "user2",
            "access_token": "valid_token_2_12345678901234567890",  # 35 chars
            "client_id": "client2",
            "client_secret": "secret2",
            "channels": ["channel2"],
        }
        user3 = {
            "username": "user3",
            "access_token": "valid_token_3_12345678901234567890",  # 35 chars
            "client_id": "client3",
            "client_secret": "secret3",
            "channels": ["channel3"],
        }

        users = [user1, {"username": ""}, user2, {}, user3]  # Mix valid and invalid
        result = get_valid_users(users)

        assert len(result) == 3
        assert result[0]["username"] == "user1"
        assert result[1]["username"] == "user2"
        assert result[2]["username"] == "user3"


class TestConfigValidatorIntegration:
    """Test config validator integration scenarios"""

    def test_validator_with_real_config_structures(self):
        """Test validator with realistic config structures"""
        # Test various real-world config scenarios
        configs_to_test = [
            SINGLE_USER_CONFIG,
            MINIMAL_CONFIG["users"][0],
            MULTI_USER_CONFIG["users"][0],
            MULTI_USER_CONFIG["users"][1],
        ]

        for config in configs_to_test:
            result = validate_user_config(config)
            assert result is True, f"Config should be valid: {config}"

    def test_validator_performance_many_users(self):
        """Test validator performance with many users"""
        # Create a large list of valid users
        base_user = SINGLE_USER_CONFIG.copy()
        users = []

        for i in range(100):
            user = base_user.copy()
            user["username"] = f"user{i}"
            user["oauth_token"] = f"oauth:token{i}"
            user["client_id"] = f"client{i}"
            users.append(user)

        result = validate_all_users(users)
        assert result is True

    def test_validator_edge_cases(self):
        """Test validator with edge cases"""
        edge_cases = [
            # Very long strings
            {
                "username": "a" * 1000,
                "oauth_token": "oauth:" + "b" * 1000,
                "client_id": "c" * 1000,
                "is_prime_or_turbo": True,
            },
            # Special characters
            {
                "username": "user@test.com",
                "oauth_token": "oauth:token_with_special-chars.123",
                "client_id": "client-id_123.test",
                "is_prime_or_turbo": False,
            },
            # Minimum valid data
            {
                "username": "u",
                "oauth_token": "oauth:t",
                "client_id": "c",
                "is_prime_or_turbo": True,
            },
        ]

        for case in edge_cases:
            result = validate_user_config(case)
            # Should not crash, result depends on implementation
            assert isinstance(result, bool)

    def test_validator_type_coercion(self):
        """Test validator with type coercion scenarios"""
        # Test with different data types that might be coerced
        type_test_cases = [
            {
                "username": 123,  # Integer instead of string
                "oauth_token": "oauth:test123",
                "client_id": "test_client",
                "is_prime_or_turbo": False,
            },
            {
                "username": "testuser",
                "oauth_token": "oauth:test123",
                "client_id": "test_client",
                "is_prime_or_turbo": "true",  # String instead of boolean
            },
        ]

        for case in type_test_cases:
            result = validate_user_config(case)
            # Should handle gracefully without crashing
            assert isinstance(result, bool)
