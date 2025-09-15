from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.message_processor import MessageProcessor


@pytest.mark.asyncio
async def test_handle_message_invalid_sender():
    """Test handle_message ignores messages from non-bot users."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_maybe_handle_toggle', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_maybe_handle_ccc', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_is_color_change_allowed', return_value=False):
        await processor.handle_message("otheruser", "#channel", "message")
        # Should not call any handlers
        processor._maybe_handle_toggle.assert_not_called()
        processor._maybe_handle_ccc.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_handle_ccc_invalid_command():
    """Test _maybe_handle_ccc returns False for non-ccc commands."""
    mock_bot = MagicMock()
    processor = MessageProcessor(mock_bot)
    result = await processor._maybe_handle_ccc("notccc", "notccc")
    assert result is False


@pytest.mark.asyncio
async def test_maybe_handle_ccc_hex_non_prime_user():
    """Test _maybe_handle_ccc ignores hex for non-Prime users."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.use_random_colors = False
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.logging') as mock_logging:
        result = await processor._maybe_handle_ccc("ccc #ff0000", "ccc #ff0000")
        assert result is True
        mock_logging.info.assert_called_with(
            "ℹ️ Ignoring hex via ccc for non-Prime user=testuser color=#ff0000"
        )


@pytest.mark.asyncio
async def test_maybe_handle_ccc_preset_case_insensitive():
    """Test _maybe_handle_ccc handles preset names case-insensitively."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.use_random_colors = True
    mock_bot.color_changer._change_color = AsyncMock()
    processor = MessageProcessor(mock_bot)
    result = await processor._maybe_handle_ccc("ccc BLUE", "ccc blue")
    assert result is True
    mock_bot.color_changer._change_color.assert_called_once_with("blue")


def test_normalize_color_arg_invalid_hex():
    """Test _normalize_color_arg returns None for invalid hex."""
    result = MessageProcessor._normalize_color_arg("invalid")
    assert result is None


def test_normalize_color_arg_unknown_preset():
    """Test _normalize_color_arg returns None for unknown preset."""
    result = MessageProcessor._normalize_color_arg("unknowncolor")
    assert result is None


@pytest.mark.asyncio
async def test_maybe_handle_toggle_redundant_command():
    """Test _maybe_handle_toggle handles redundant commands."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.enabled = True
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_persist_enabled_flag', new_callable=AsyncMock):
        result = await processor._maybe_handle_toggle("cce")
        assert result is True
        processor._persist_enabled_flag.assert_not_called()


@pytest.mark.asyncio
async def test_persist_enabled_flag_config_error():
    """Test _persist_enabled_flag handles config errors gracefully."""
    mock_bot = MagicMock()
    mock_bot.config_file = "config.json"
    mock_bot._build_user_config.return_value = {"enabled": True}
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.queue_user_update', side_effect=Exception("Config error")), \
          patch('src.bot.message_processor.logging') as mock_logging:
        await processor._persist_enabled_flag(True)
        mock_logging.warning.assert_called_with("Persist flag error: Config error")


@pytest.mark.asyncio
async def test_handle_message_toggle_handled():
    """Test handle_message when toggle command is handled."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_maybe_handle_toggle', new_callable=AsyncMock, return_value=True), \
         patch.object(processor, '_maybe_handle_ccc', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_is_color_change_allowed', return_value=False):
        await processor.handle_message("testuser", "#channel", "cce")
        processor._maybe_handle_toggle.assert_called_once_with("cce")
        processor._maybe_handle_ccc.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_ccc_handled():
    """Test handle_message when ccc command is handled."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_maybe_handle_toggle', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_maybe_handle_ccc', new_callable=AsyncMock, return_value=True), \
         patch.object(processor, '_is_color_change_allowed', return_value=False):
        await processor.handle_message("testuser", "#channel", "ccc blue")
        processor._maybe_handle_toggle.assert_called_once_with("ccc blue")
        processor._maybe_handle_ccc.assert_called_once_with("ccc blue", "ccc blue")


@pytest.mark.asyncio
async def test_handle_message_auto_change():
    """Test handle_message triggers auto color change."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.color_changer._change_color = AsyncMock()
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_maybe_handle_toggle', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_maybe_handle_ccc', new_callable=AsyncMock, return_value=False), \
         patch.object(processor, '_is_color_change_allowed', return_value=True):
        await processor.handle_message("testuser", "#channel", "random message")
        mock_bot.color_changer._change_color.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_exception():
    """Test handle_message handles exceptions gracefully."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_maybe_handle_toggle', side_effect=Exception("Toggle error")), \
         patch('src.bot.message_processor.logging') as mock_logging:
        await processor.handle_message("testuser", "#channel", "cce")
        mock_logging.error.assert_called_with("Error handling message from testuser: Toggle error")


def test_is_color_change_allowed_true():
    """Test _is_color_change_allowed returns True when enabled."""
    mock_bot = MagicMock()
    mock_bot.enabled = True
    processor = MessageProcessor(mock_bot)
    assert processor._is_color_change_allowed() is True


def test_is_color_change_allowed_false():
    """Test _is_color_change_allowed returns False when disabled."""
    mock_bot = MagicMock()
    mock_bot.enabled = False
    processor = MessageProcessor(mock_bot)
    assert processor._is_color_change_allowed() is False


@pytest.mark.asyncio
async def test_maybe_handle_ccc_missing_arg():
    """Test _maybe_handle_ccc with missing argument."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.logging') as mock_logging:
        result = await processor._maybe_handle_ccc("ccc", "ccc")
        assert result is True
        mock_logging.info.assert_called_with("ℹ️ Ignoring invalid ccc command (missing argument) user=testuser")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_invalid_arg():
    """Test _maybe_handle_ccc with invalid argument."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.logging') as mock_logging:
        result = await processor._maybe_handle_ccc("ccc invalid", "ccc invalid")
        assert result is True
        mock_logging.info.assert_called_with("ℹ️ Ignoring invalid ccc argument user=testuser arg=invalid")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_hex_prime():
    """Test _maybe_handle_ccc with valid hex for Prime user."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.use_random_colors = True
    mock_bot.color_changer._change_color = AsyncMock()
    processor = MessageProcessor(mock_bot)
    result = await processor._maybe_handle_ccc("ccc #ff0000", "ccc #ff0000")
    assert result is True
    mock_bot.color_changer._change_color.assert_called_once_with("#ff0000")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_preset():
    """Test _maybe_handle_ccc with valid preset."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.use_random_colors = True
    mock_bot.color_changer._change_color = AsyncMock()
    processor = MessageProcessor(mock_bot)
    result = await processor._maybe_handle_ccc("ccc blue", "ccc blue")
    assert result is True
    mock_bot.color_changer._change_color.assert_called_once_with("blue")


def test_normalize_color_arg_valid_hex_6():
    """Test _normalize_color_arg with valid 6-digit hex."""
    result = MessageProcessor._normalize_color_arg("#ff0000")
    assert result == "#ff0000"


def test_normalize_color_arg_valid_hex_3():
    """Test _normalize_color_arg with valid 3-digit hex."""
    result = MessageProcessor._normalize_color_arg("#abc")
    assert result == "#aabbcc"


def test_normalize_color_arg_valid_preset():
    """Test _normalize_color_arg with valid preset."""
    result = MessageProcessor._normalize_color_arg("blue")
    assert result == "blue"


def test_normalize_color_arg_with_hash():
    """Test _normalize_color_arg with hash prefix."""
    result = MessageProcessor._normalize_color_arg("#123456")
    assert result == "#123456"


@pytest.mark.asyncio
async def test_maybe_handle_toggle_enable():
    """Test _maybe_handle_toggle enables when disabled."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.enabled = False
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_persist_enabled_flag', new_callable=AsyncMock), \
         patch('src.bot.message_processor.logging') as mock_logging:
        result = await processor._maybe_handle_toggle("cce")
        assert result is True
        assert mock_bot.enabled is True
        mock_logging.info.assert_called_with("🖍️ Automatic color change enabled for user testuser")
        processor._persist_enabled_flag.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_maybe_handle_toggle_disable():
    """Test _maybe_handle_toggle disables when enabled."""
    mock_bot = MagicMock()
    mock_bot.username = "testuser"
    mock_bot.enabled = True
    processor = MessageProcessor(mock_bot)
    with patch.object(processor, '_persist_enabled_flag', new_callable=AsyncMock), \
         patch('src.bot.message_processor.logging') as mock_logging:
        result = await processor._maybe_handle_toggle("ccd")
        assert result is True
        assert mock_bot.enabled is False
        mock_logging.info.assert_called_with("🚫 Automatic color change disabled for user testuser")
        processor._persist_enabled_flag.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_persist_enabled_flag_success():
    """Test _persist_enabled_flag succeeds."""
    mock_bot = MagicMock()
    mock_bot.config_file = "config.json"
    mock_bot._build_user_config.return_value = {"enabled": True}
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.queue_user_update', new_callable=AsyncMock) as mock_queue:
        await processor._persist_enabled_flag(True)
        mock_queue.assert_called_once_with({"enabled": True}, "config.json")


@pytest.mark.asyncio
async def test_persist_enabled_flag_no_config():
    """Test _persist_enabled_flag with no config file."""
    mock_bot = MagicMock()
    mock_bot.config_file = None
    processor = MessageProcessor(mock_bot)
    with patch('src.bot.message_processor.queue_user_update', new_callable=AsyncMock) as mock_queue:
        await processor._persist_enabled_flag(True)
        mock_queue.assert_not_called()
