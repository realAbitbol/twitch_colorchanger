"""Pytest conftest for test-time shims and fixtures.

This file preloads certain package modules to ensure a canonical
import identity (prevents coverage from recording the same file under
two different module names like `simple_irc.py` and `src/simple_irc.py`).
"""
import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, Mock

import pytest

try:
    # Import the canonical package module early in collection
    import src.simple_irc as _simple_irc

    # Ensure aliases exist so imports under either name refer to the same module
    if 'simple_irc' not in sys.modules:
        sys.modules['simple_irc'] = _simple_irc
    if 'src.simple_irc' not in sys.modules:
        sys.modules['src.simple_irc'] = _simple_irc
except Exception:
    # Be defensive: don't fail test collection if import fails for any reason
    pass
"""
Pytest configuration and shared fixtures for the Twitch ColorChanger Bot tests
"""


# Test event loop configuration for async tests

@pytest.fixture(scope="function")
def event_loop():
    """Create an instance of the default event loop for each test function."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    try:
        _cancel_all_tasks(loop)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
    finally:
        loop.close()


def _cancel_all_tasks(loop):
    """Cancel all pending tasks in the event loop."""
    to_cancel = asyncio.all_tasks(loop)
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))


# Configuration fixtures
@pytest.fixture
def sample_user_config():
    """Sample user configuration for testing"""
    return {
        "username": "testuser",
        "client_id": "test_client_id_123",
        "client_secret": "test_client_secret_456",
        "access_token": "test_access_token_789",
        "refresh_token": "test_refresh_token_abc",
        "channels": ["testchannel1", "testchannel2"],
        "is_prime_or_turbo": True
    }


@pytest.fixture
def sample_multi_user_config(sample_user_config):
    """Sample multi-user configuration for testing"""
    user2 = sample_user_config.copy()
    user2.update({
        "username": "testuser2",
        "client_id": "test_client_id_456",
        "access_token": "test_access_token_def",
        "is_prime_or_turbo": False
    })

    return {
        "users": [sample_user_config, user2]
    }


@pytest.fixture
def temp_config_file(sample_multi_user_config):
    """Create a temporary config file for testing"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
        json.dump(sample_multi_user_config, f, indent=2)
        temp_file = f.name

    yield temp_file

    # Cleanup
    if os.path.exists(temp_file):
        os.unlink(temp_file)


@pytest.fixture
def invalid_config_file():
    """Create a temporary invalid config file for testing"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
        f.write("invalid json content {")
        temp_file = f.name

    yield temp_file

    # Cleanup
    if os.path.exists(temp_file):
        os.unlink(temp_file)


# Mock fixtures
@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession for API testing"""
    session = Mock()
    session.request = AsyncMock()
    return session


@pytest.fixture
def mock_twitch_api_response():
    """Mock successful Twitch API response"""
    def _mock_response(status=200, data=None, headers=None):
        response = Mock()
        response.status = status
        response.json = AsyncMock(return_value=data or {})
        response.headers = headers or {}
        return response

    return _mock_response


@pytest.fixture
def mock_user_info_response():
    """Mock Twitch user info API response"""
    return {
        "data": [{
            "id": "12345678",
            "login": "testuser",
            "display_name": "TestUser",
            "type": "",
            "broadcaster_type": "partner",
            "description": "Test user description",
            "profile_image_url": "https://example.com/avatar.png",
            "offline_image_url": "",
            "view_count": 1000,
            "created_at": "2023-01-01T00:00:00Z"
        }]
    }


@pytest.fixture
def mock_color_response():
    """Mock Twitch color API response"""
    return {
        "data": [{
            "user_id": "12345678",
            "user_login": "testuser",
            "user_name": "TestUser",
            "color": "#FF0000"
        }]
    }


@pytest.fixture
def mock_token_refresh_response():
    """Mock token refresh API response"""
    return {
        "access_token": "new_access_token_123",
        "refresh_token": "new_refresh_token_456",
        "expires_in": 14400,  # 4 hours
        "scope": ["chat:read", "user:manage:chat_color"],
        "token_type": "bearer"
    }


@pytest.fixture
def mock_irc_socket():
    """Mock IRC socket for testing"""
    socket_mock = Mock()
    socket_mock.connect = Mock()
    socket_mock.send = Mock()
    socket_mock.recv = Mock(return_value=b":tmi.twitch.tv 001 testuser :Welcome\r\n")
    socket_mock.settimeout = Mock()
    return socket_mock


# Bot fixtures
@pytest.fixture
def bot_config():
    """Basic bot configuration"""
    return {
        "token": "test_token",
        "refresh_token": "test_refresh",
        "client_id": "test_client",
        "client_secret": "test_secret",
        "nick": "testuser",
        "channels": ["testchannel"],
        "is_prime_or_turbo": True,
        "config_file": "test_config.conf",
        "user_id": "12345678"
    }


# Environment fixtures
@pytest.fixture
def clean_environment():
    """Clean environment variables for testing"""
    original_env = os.environ.copy()

    # Remove any environment variables that might affect tests
    env_vars_to_remove = ['TWITCH_CONF_FILE', 'DEBUG']
    for var in env_vars_to_remove:
        os.environ.pop(var, None)

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# Async test helpers
@pytest.fixture
def async_mock():
    """Create AsyncMock for async function mocking"""
    return AsyncMock()


# Rate limiter fixtures
@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter for testing"""
    limiter = Mock()
    limiter.wait_if_needed = AsyncMock()
    limiter.update_from_headers = Mock()
    return limiter


# Color fixtures
@pytest.fixture
def sample_hex_colors():
    """Sample hex colors for testing"""
    return ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"]


@pytest.fixture
def sample_preset_colors():
    """Sample Twitch preset colors for testing"""
    return ["Blue", "BlueViolet", "CadetBlue", "Chocolate", "Coral", "DodgerBlue"]


# Configuration for pytest
def pytest_configure(config):
    """Configure pytest settings"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


# Test data cleanup
@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Automatically clean up any test files created during testing"""
    yield

    # Cleanup any test files that might have been created
    test_files = [
        "test_config.conf",
        "test_config.conf.backup",
        "debug_test.py"
    ]

    for file in test_files:
        if os.path.exists(file):
            try:
                os.unlink(file)
            except OSError:
                pass  # Ignore cleanup errors
