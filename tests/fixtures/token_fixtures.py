"""
Fixtures for token-related data.
"""

from datetime import datetime, timedelta
from typing import Dict, Any

# Mock valid token
MOCK_VALID_TOKEN = {
    "access_token": "mock_access_token_123",
    "refresh_token": "mock_refresh_token_456",
    "expires_at": datetime.now() + timedelta(hours=1),
    "token_type": "bearer",
    "scope": ["chat:read", "chat:edit"]
}

# Mock expired token
MOCK_EXPIRED_TOKEN = {
    "access_token": "mock_expired_token_123",
    "refresh_token": "mock_refresh_token_456",
    "expires_at": datetime.now() - timedelta(hours=1),
    "token_type": "bearer",
    "scope": ["chat:read", "chat:edit"]
}

# Mock token response from Twitch API
MOCK_TOKEN_RESPONSE = {
    "access_token": "new_mock_access_token_789",
    "refresh_token": "new_mock_refresh_token_012",
    "expires_in": 3600,
    "token_type": "bearer",
    "scope": ["chat:read", "chat:edit"]
}

# Mock invalid token response
MOCK_INVALID_TOKEN_RESPONSE = {
    "error": "invalid_grant",
    "error_description": "Invalid refresh token",
    "status": 400
}

# Mock token validation response
MOCK_TOKEN_VALIDATION = {
    "client_id": "mock_client_id",
    "login": "testuser",
    "scopes": ["chat:read", "chat:edit"],
    "user_id": "123456",
    "expires_in": 3600
}

def get_mock_token(token_type: str = "valid") -> Dict[str, Any]:
    """Get mock token data."""
    tokens = {
        "valid": MOCK_VALID_TOKEN,
        "expired": MOCK_EXPIRED_TOKEN
    }
    return tokens.get(token_type, MOCK_VALID_TOKEN)