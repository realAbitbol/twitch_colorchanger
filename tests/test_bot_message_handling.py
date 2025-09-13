from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.core import TwitchColorBot


@pytest.mark.asyncio
async def test_handle_message_wrong_sender():
    """Test handle_message ignores messages from wrong sender."""
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

    await bot.handle_message("otheruser", "#test", "hello")


@pytest.mark.asyncio
async def test_handle_message_toggle_handled():
    """Test handle_message when toggle is handled."""
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

    with patch.object(bot, "_maybe_handle_toggle", return_value=True) as mock_toggle:
        await bot.handle_message("testuser", "#test", "ccd")

        mock_toggle.assert_called_once_with("ccd")


@pytest.mark.asyncio
async def test_handle_message_ccc_handled():
    """Test handle_message when CCC is handled."""
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

    with patch.object(bot, "_maybe_handle_toggle", return_value=False) as mock_toggle, \
         patch.object(bot, "_maybe_handle_ccc", return_value=True) as mock_ccc:
        await bot.handle_message("testuser", "#test", "ccc red")

        mock_toggle.assert_called_once_with("ccc red")
        mock_ccc.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_color_change():
    """Test handle_message triggers color change."""
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
        enabled=True,
    )

    with patch.object(bot, "_maybe_handle_toggle", return_value=False) as mock_toggle, \
         patch.object(bot, "_maybe_handle_ccc", return_value=False) as mock_ccc, \
         patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        await bot.handle_message("testuser", "#test", "hello")

        mock_toggle.assert_called_once_with("hello")
        mock_ccc.assert_called_once()
        mock_change.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_disabled():
    """Test handle_message does not trigger color change when disabled."""
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
        enabled=False,
    )

    with patch.object(bot, "_maybe_handle_toggle", return_value=False) as mock_toggle, \
         patch.object(bot, "_maybe_handle_ccc", return_value=False) as mock_ccc, \
         patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        await bot.handle_message("testuser", "#test", "hello")

        mock_toggle.assert_called_once_with("hello")
        mock_ccc.assert_called_once()
        mock_change.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_handle_toggle_not_toggle():
    """Test _maybe_handle_toggle for non-toggle message."""
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
        enabled=True,
    )

    result = await bot._maybe_handle_toggle("hello")

    assert result is False
    assert bot.enabled is True


@pytest.mark.asyncio
async def test_maybe_handle_toggle_ccd():
    """Test _maybe_handle_toggle for ccd."""
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
        enabled=True,
    )

    with patch.object(bot, "_persist_enabled_flag", new_callable=AsyncMock) as mock_persist:
        result = await bot._maybe_handle_toggle("ccd")

        assert result is True
        assert bot.enabled is False
        mock_persist.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_maybe_handle_toggle_cce():
    """Test _maybe_handle_toggle for cce."""
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
        enabled=False,
    )

    with patch.object(bot, "_persist_enabled_flag", new_callable=AsyncMock) as mock_persist:
        result = await bot._maybe_handle_toggle("cce")

        assert result is True
        assert bot.enabled is True
        mock_persist.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_maybe_handle_toggle_already_disabled():
    """Test _maybe_handle_toggle for ccd when already disabled."""
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
        enabled=False,
    )

    with patch.object(bot, "_persist_enabled_flag", new_callable=AsyncMock) as mock_persist:
        result = await bot._maybe_handle_toggle("ccd")

        assert result is True
        assert bot.enabled is False
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_preset():
    """Test _maybe_handle_ccc with valid preset."""
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
        is_prime_or_turbo=True,
    )

    with patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await bot._maybe_handle_ccc("ccc red", "ccc red")

        assert result is True
        mock_change.assert_called_once_with("red")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_hex():
    """Test _maybe_handle_ccc with valid hex."""
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
        is_prime_or_turbo=True,
    )

    with patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await bot._maybe_handle_ccc("ccc #123456", "ccc #123456")

        assert result is True
        mock_change.assert_called_once_with("#123456")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_not_ccc():
    """Test _maybe_handle_ccc with non-ccc message."""
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

    result = await bot._maybe_handle_ccc("hello", "hello")

    assert result is False


@pytest.mark.asyncio
async def test_maybe_handle_ccc_no_arg():
    """Test _maybe_handle_ccc with no argument."""
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

    result = await bot._maybe_handle_ccc("ccc", "ccc")

    assert result is True  # Handled but invalid


@pytest.mark.asyncio
async def test_maybe_handle_ccc_invalid_color():
    """Test _maybe_handle_ccc with invalid color."""
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
        is_prime_or_turbo=True,
    )

    with patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await bot._maybe_handle_ccc("ccc invalid", "ccc invalid")

        assert result is True
        mock_change.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_handle_ccc_hex_non_prime():
    """Test _maybe_handle_ccc with hex for non-prime user."""
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
        is_prime_or_turbo=False,
    )

    with patch.object(bot, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await bot._maybe_handle_ccc("ccc #123456", "ccc #123456")

        assert result is True
        mock_change.assert_not_called()
