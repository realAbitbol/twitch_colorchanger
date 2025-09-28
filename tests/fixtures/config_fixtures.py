"""
Fixtures for configuration data.
"""

from typing import Dict, Any, List

# Mock user configuration
MOCK_USER_CONFIG = {
    "username": "testuser",
    "color": "#FF0000",
    "token": "mock_token_123",
    "enabled": True
}

# Mock full configuration with multiple users
MOCK_FULL_CONFIG = {
    "users": [
        {
            "username": "testuser1",
            "color": "#FF0000",
            "token": "mock_token_1",
            "enabled": True
        },
        {
            "username": "testuser2",
            "color": "#00FF00",
            "token": "mock_token_2",
            "enabled": False
        },
        {
            "username": "testuser3",
            "color": "#0000FF",
            "token": "mock_token_3",
            "enabled": True
        }
    ]
}

# Mock invalid configuration
MOCK_INVALID_CONFIG = {
    "users": [
        {
            "username": "",  # Invalid: empty username
            "color": "#FF0000",
            "token": "mock_token_1",
            "enabled": True
        },
        {
            "username": "testuser2",
            "color": "invalid_color",  # Invalid: not a hex color
            "token": "mock_token_2",
            "enabled": False
        }
    ]
}

# Mock configuration file content as string
MOCK_CONFIG_FILE_CONTENT = """
users:
  - username: testuser1
    color: "#FF0000"
    token: mock_token_1
    enabled: true
  - username: testuser2
    color: "#00FF00"
    token: mock_token_2
    enabled: false
"""

def get_mock_config_as_dict(config_type: str = "full") -> Dict[str, Any]:
    """Get mock configuration as dictionary."""
    configs = {
        "single": {"users": [MOCK_USER_CONFIG]},
        "full": MOCK_FULL_CONFIG,
        "invalid": MOCK_INVALID_CONFIG
    }
    return configs.get(config_type, MOCK_FULL_CONFIG)