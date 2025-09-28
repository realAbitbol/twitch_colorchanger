"""
Fixtures for Twitch API responses and events.
"""

import json
from typing import Dict, Any

# Mock Twitch EventSub message for color change
MOCK_COLOR_CHANGE_MESSAGE = {
    "metadata": {
        "message_id": "test-message-id",
        "message_type": "notification",
        "message_timestamp": "2023-01-01T00:00:00Z",
        "subscription_type": "channel.update",
        "subscription_version": "1"
    },
    "payload": {
        "subscription": {
            "id": "test-subscription-id",
            "status": "enabled",
            "type": "channel.update",
            "version": "1",
            "condition": {
                "broadcaster_user_id": "123456"
            },
            "transport": {
                "method": "websocket",
                "session_id": "test-session-id"
            },
            "created_at": "2023-01-01T00:00:00Z"
        },
        "event": {
            "broadcaster_user_id": "123456",
            "broadcaster_user_login": "testuser",
            "broadcaster_user_name": "TestUser",
            "stream_type": "live",
            "started_at": "2023-01-01T00:00:00Z"
        }
    }
}

# Mock WebSocket welcome message
MOCK_WELCOME_MESSAGE = {
    "metadata": {
        "message_id": "test-welcome-id",
        "message_type": "session_welcome",
        "message_timestamp": "2023-01-01T00:00:00Z"
    },
    "payload": {
        "session": {
            "id": "test-session-id",
            "status": "connected",
            "connected_at": "2023-01-01T00:00:00Z",
            "keepalive_timeout_seconds": 10,
            "reconnect_url": None
        }
    }
}

# Mock keepalive message
MOCK_KEEPALIVE_MESSAGE = {
    "metadata": {
        "message_id": "test-keepalive-id",
        "message_type": "session_keepalive",
        "message_timestamp": "2023-01-01T00:00:00Z"
    },
    "payload": {}
}

# Mock reconnect message
MOCK_RECONNECT_MESSAGE = {
    "metadata": {
        "message_id": "test-reconnect-id",
        "message_type": "session_reconnect",
        "message_timestamp": "2023-01-01T00:00:00Z"
    },
    "payload": {
        "session": {
            "id": "test-session-id",
            "status": "reconnecting",
            "connected_at": "2023-01-01T00:00:00Z",
            "keepalive_timeout_seconds": 10,
            "reconnect_url": "wss://eventsub.wss.twitch.tv?session_id=test-session-id"
        }
    }
}

def get_mock_message_json(message_type: str) -> str:
    """Get mock message as JSON string."""
    messages = {
        "color_change": MOCK_COLOR_CHANGE_MESSAGE,
        "welcome": MOCK_WELCOME_MESSAGE,
        "keepalive": MOCK_KEEPALIVE_MESSAGE,
        "reconnect": MOCK_RECONNECT_MESSAGE
    }
    return json.dumps(messages.get(message_type, {}))