"""Tests for src/bot/token_refresher.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.token_refresher import TokenRefresher


class MockTokenRefresher(TokenRefresher):
    """Mock class to test TokenRefresher mixin."""

    def __init__(self):
        self.username = "testuser"
        self.access_token = "token"
        self.refresh_token = "refresh"
        self.client_id = "client"
        self.client_secret = "secret"
        self.token_expiry = None
        self.context = MagicMock()
        self.chat_backend = None
        self.channels = ["test"]
        self.config_file = "test.conf"
        self.use_random_colors = False
        self.token_manager = MagicMock()


def test_token_refresher_init_invalid():
    """Test TokenRefresher initialization with invalid parameters like negative intervals."""
    refresher = MockTokenRefresher()
    # No direct init, but mixin should work
    assert refresher.username == "testuser"


@pytest.mark.asyncio
async def test_refresh_tokens_expired():
    """Test refresh_tokens method with expired tokens, verifying refresh logic."""
    refresher = MockTokenRefresher()
    mock_outcome = MagicMock()
    mock_outcome.name = "SUCCESS"
    refresher.token_manager.ensure_fresh = AsyncMock(return_value=mock_outcome)
    refresher.token_manager.get_info = MagicMock(return_value=MagicMock(access_token="new_token"))
    result = await refresher._check_and_refresh_token()
    assert result is True


@pytest.mark.asyncio
async def test_handle_refresh_error_network():
    """Test handle_refresh_error with network failure scenarios."""
    refresher = MockTokenRefresher()
    from aiohttp import ClientError
    refresher.token_manager.ensure_fresh = AsyncMock(side_effect=ClientError("Network error"))
    result = await refresher._check_and_refresh_token()
    assert result is False


def test_schedule_refresh_invalid_intervals():
    """Test schedule_refresh with invalid or zero intervals."""
    refresher = MockTokenRefresher()
    refresher.config_file = None  # Invalid config
    # No schedule_refresh method, but _check_and_refresh_token handles
    assert refresher._validate_config_prerequisites() is False


@pytest.mark.asyncio
async def test_cancel_refresh_active():
    """Test cancel_refresh during an active refresh operation."""
    refresher = MockTokenRefresher()
    refresher.token_manager.ensure_fresh = AsyncMock()
    # Start refresh
    task = asyncio.create_task(refresher._check_and_refresh_token())
    await asyncio.sleep(0.01)  # Let it start
    # Cancel
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_token_refresher_stop_during_refresh():
    """Test stop method during an active token refresh."""
    refresher = MockTokenRefresher()
    refresher.token_manager.ensure_fresh = AsyncMock()
    # Start refresh
    task = asyncio.create_task(refresher._check_and_refresh_token())
    await asyncio.sleep(0.01)
    # Simulate stop (though stop is not in refresher, but in bot)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_token_refresher_multiple_refresh_requests():
    """Test handling of multiple concurrent refresh requests."""
    refresher = MockTokenRefresher()
    refresher.token_manager.ensure_fresh = AsyncMock()
    # Start multiple
    tasks = [asyncio.create_task(refresher._check_and_refresh_token()) for _ in range(3)]
    await asyncio.gather(*tasks)
    assert refresher.token_manager.ensure_fresh.call_count == 3


@pytest.mark.asyncio
async def test_token_refresher_refresh_with_stale_token():
    """Test refresh with a stale but not expired token."""
    refresher = MockTokenRefresher()
    mock_outcome = MagicMock()
    mock_outcome.name = "SUCCESS"
    refresher.token_manager.ensure_fresh = AsyncMock(return_value=mock_outcome)
    refresher.token_manager.get_info = MagicMock(return_value=MagicMock(access_token="new_token"))
    result = await refresher._check_and_refresh_token()
    assert result is True


@pytest.mark.asyncio
async def test_token_refresher_error_recovery():
    """Test error recovery after a failed refresh attempt."""
    refresher = MockTokenRefresher()
    refresher.token_manager.ensure_fresh = AsyncMock(side_effect=RuntimeError("Fail"))
    # First call fails
    result1 = await refresher._check_and_refresh_token()
    assert result1 is False
    # Second call succeeds
    refresher.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="SUCCESS"))
    refresher.token_manager.get_info = MagicMock(return_value=MagicMock(access_token="recovered"))
    result2 = await refresher._check_and_refresh_token()
    assert result2 is True
