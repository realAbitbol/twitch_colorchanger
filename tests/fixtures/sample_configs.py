"""
Sample configuration data for testing
"""

# Valid single user configuration (legacy format)
SINGLE_USER_CONFIG = {
    "username": "testuser",
    "client_id": "abcdefghij1234567890",
    "client_secret": "klmnopqrst0987654321",
    "access_token": "access_token_example_123",
    "refresh_token": "refresh_token_example_456",
    "channels": ["channel1", "channel2", "testuser"],
    "is_prime_or_turbo": True,
}

# Valid multi-user configuration
MULTI_USER_CONFIG = {
    "users": [
        {
            "username": "primeuser",
            "client_id": "prime_client_id_123",
            "client_secret": "prime_client_secret_456",
            "access_token": "prime_access_token_789",
            "refresh_token": "prime_refresh_token_abc",
            "channels": ["bigstreamer", "primeuser"],
            "is_prime_or_turbo": True,
        },
        {
            "username": "regularuser",
            "client_id": "regular_client_id_456",
            "client_secret": "regular_client_secret_789",
            "access_token": "regular_access_token_def",
            "refresh_token": "regular_refresh_token_ghi",
            "channels": ["smallstreamer", "regularuser"],
            "is_prime_or_turbo": False,
        },
    ]
}

# Invalid configurations for testing validation
INVALID_CONFIGS = {
    "missing_username": {
        "users": [
            {
                "client_id": "test_client",
                "client_secret": "test_secret",
                "channels": ["test"],
            }
        ]
    },
    "empty_channels": {
        "users": [
            {
                "username": "testuser",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "channels": [],
            }
        ]
    },
    "invalid_prime_flag": {
        "users": [
            {
                "username": "testuser",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "channels": ["test"],
                "is_prime_or_turbo": "not_boolean",
            }
        ]
    },
    "malformed_json": '{"users": [{"username": "test"',
}

# Minimal valid configuration
MINIMAL_CONFIG = {
    "users": [
        {
            "username": "testuser",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "channels": ["testchannel"],
        }
    ]
}

# Configuration with missing tokens (for device flow testing)
CONFIG_MISSING_TOKENS = {
    "users": [
        {
            "username": "newuser",
            "client_id": "new_client_id",
            "client_secret": "new_client_secret",
            "channels": ["newchannel"],
            "is_prime_or_turbo": True,
        }
    ]
}
