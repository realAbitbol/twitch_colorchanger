from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot


@pytest.mark.asyncio
async def test_attempt_reconnect_success():
    """Test _attempt_reconnect success on first try."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )
    bot.running = True
    bot.listener_task = MagicMock()

    mock_backend = MagicMock()
    mock_backend.listen = AsyncMock()
    bot.chat_backend = mock_backend

    error = RuntimeError("Test error")

    with patch.object(bot, "_initialize_connection", side_effect=[False, True]) as mock_init, \
         patch.object(bot.listener_task, "add_done_callback") as mock_cb:
        # First call fails, second succeeds
        await bot._attempt_reconnect(error, lambda t: None)

        assert mock_init.call_count == 2
        mock_backend.listen.assert_called_once()


@pytest.mark.asyncio
async def test_attempt_reconnect_failure():
    """Test _attempt_reconnect failure after max attempts."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )
    bot.running = True

    error = RuntimeError("Test error")

    with patch.object(bot, "_initialize_connection", return_value=False) as mock_init, \
         patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        await bot._attempt_reconnect(error, lambda t: None)

        assert mock_init.call_count == 5  # max_attempts


@pytest.mark.asyncio
async def test_check_and_refresh_token_success():
    """Test _check_and_refresh_token success."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="old_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )

    mock_tm = MagicMock()
    mock_info = MagicMock()
    mock_info.access_token = "new_token"
    mock_info.refresh_token = "new_refresh"
    mock_outcome = MagicMock()
    mock_outcome.name = "SUCCESS"
    mock_tm.ensure_fresh = AsyncMock(return_value=mock_outcome)
    mock_tm.get_info = MagicMock(return_value=mock_info)
    bot.token_manager = mock_tm

    mock_backend = MagicMock()
    bot.chat_backend = mock_backend

    result = await bot._check_and_refresh_token()

    assert result is True
    assert bot.access_token == "new_token"
    mock_backend.update_token.assert_called_once_with("new_token")


@pytest.mark.asyncio
async def test_check_and_refresh_token_no_manager():
    """Test _check_and_refresh_token with no token manager."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )

    result = await bot._check_and_refresh_token()

    assert result is False


@pytest.mark.asyncio
async def test_check_and_refresh_token_failure():
    """Test _check_and_refresh_token failure."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )

    mock_tm = MagicMock()
    mock_tm.ensure_fresh = AsyncMock(return_value="FAILED")
    bot.token_manager = mock_tm

    result = await bot._check_and_refresh_token()

    assert result is False


@pytest.mark.asyncio
async def test_check_and_refresh_token_no_info():
    """Test _check_and_refresh_token when get_info returns None."""
    ctx = MagicMock()
    bot = TwitchColorBot(
        context=ctx,
        token="test_token",
        refresh_token="test_refresh",
        client_id="test_client_id",
        client_secret="test_client_secret",
        nick="testuser",
        channels=["#test"],
        http_session=MagicMock(),
    )

    mock_tm = MagicMock()
    mock_tm.ensure_fresh = AsyncMock(return_value="SUCCESS")
    mock_tm.get_info = MagicMock(return_value=None)
    bot.token_manager = mock_tm

    result = await bot._check_and_refresh_token()

    assert result is False
