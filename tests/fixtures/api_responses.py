"""
Mock Twitch API responses for testing
"""

# Successful user info response
USER_INFO_SUCCESS = {
    "data": [
        {
            "id": "123456789",
            "login": "testuser",
            "display_name": "TestUser",
            "type": "",
            "broadcaster_type": "partner",
            "description": "Test user for bot testing",
            "profile_image_url": "https://example.com/avatar.png",
            "offline_image_url": "",
            "view_count": 5000,
            "created_at": "2020-01-01T00:00:00Z",
        }
    ]
}

# User not found response
USER_INFO_NOT_FOUND = {"error": "Not Found", "status": 404, "message": "User not found"}

# Current color response (Prime/Turbo user)
COLOR_RESPONSE_PRIME = {
    "data": [
        {
            "user_id": "123456789",
            "user_login": "testuser",
            "user_name": "TestUser",
            "color": "#FF5733",
        }
    ]
}

# Current color response (regular user)
COLOR_RESPONSE_REGULAR = {
    "data": [
        {
            "user_id": "987654321",
            "user_login": "regularuser",
            "user_name": "RegularUser",
            "color": "Blue",
        }
    ]
}

# No color set response
COLOR_RESPONSE_EMPTY = {"data": []}

# Token refresh success response
TOKEN_REFRESH_SUCCESS = {
    "access_token": "new_access_token_12345",
    "refresh_token": "new_refresh_token_67890",
    "expires_in": 14400,
    "scope": ["chat:read", "user:manage:chat_color"],
    "token_type": "bearer",
}

# Token refresh failure (invalid refresh token)
TOKEN_REFRESH_FAILURE = {
    "error": "Bad Request",
    "status": 400,
    "message": "Invalid refresh token",
}

# Device code flow responses
DEVICE_CODE_SUCCESS = {
    "device_code": "GMMhmHCXhwEzkoEqiMEg9d83MhNpfe22BTnWdz03C",
    "expires_in": 1800,
    "interval": 5,
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://www.twitch.tv/activate",
}

DEVICE_TOKEN_PENDING = {
    "error": "authorization_pending",
    "error_description": "The authorization request is still pending",
}

DEVICE_TOKEN_SUCCESS = {
    "access_token": "rfx2uswqe8l4g1mkagrvg5tv0ks3",
    "expires_in": 14400,
    "refresh_token": "5Ub2O6ShHGnuRl2d9KMTqN",
    "scope": ["chat:read", "user:manage:chat_color"],
    "token_type": "bearer",
}

# API error responses
UNAUTHORIZED_RESPONSE = {
    "error": "Unauthorized",
    "status": 401,
    "message": "Invalid OAuth token",
}

FORBIDDEN_RESPONSE = {
    "error": "Forbidden",
    "status": 403,
    "message": "Missing required scope",
}

RATE_LIMITED_RESPONSE = {
    "error": "Too Many Requests",
    "status": 429,
    "message": "Rate limit exceeded",
}

SERVER_ERROR_RESPONSE = {
    "error": "Internal Server Error",
    "status": 500,
    "message": "Something went wrong",
}

# Color change success response (no content)
COLOR_CHANGE_SUCCESS = ""

# Rate limit headers for testing
RATE_LIMIT_HEADERS = {
    "ratelimit-helixratelimit-remaining": "795",
    "ratelimit-helixratelimit-reset": "1640995200",
    "ratelimit-helixratelimit-limit": "800",
}

RATE_LIMIT_EXHAUSTED_HEADERS = {
    "ratelimit-helixratelimit-remaining": "0",
    "ratelimit-helixratelimit-reset": "1640995260",
    "ratelimit-helixratelimit-limit": "800",
}
