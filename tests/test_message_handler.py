from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.message_handler import MessageHandler


class MockMessageHandler(MessageHandler):
    """Test implementation of MessageHandler mixin."""

    def __init__(self):
        self.username = "testuser"
        self.enabled = True
        self.config_file = None
        self.use_random_colors = True

    async def _change_color(self, color: str | None = None) -> None:
        await asyncio.sleep(0)  # Use async feature to satisfy linter

    def _build_user_config(self) -> dict:
        return {"enabled": self.enabled}


@pytest.fixture
def handler():
    return MockMessageHandler()


# Tests for handle_message exception handling
@pytest.mark.asyncio
async def test_handle_message_exception_handling(handler):
    """Test that exceptions in handle_message are caught and logged."""
    with patch.object(handler, "_maybe_handle_toggle", side_effect=Exception("Test error")), \
         patch("src.bot.message_handler.logging.error") as mock_error:
        await handler.handle_message("testuser", "#channel", "message")
        mock_error.assert_called_once_with("Error handling message from testuser: Test error")


@pytest.mark.asyncio
async def test_handle_message_no_exception(handler):
    """Test handle_message processes normally without exceptions."""
    with patch.object(handler, "_maybe_handle_toggle", return_value=False), \
         patch.object(handler, "_maybe_handle_ccc", return_value=False), \
         patch.object(handler, "_is_color_change_allowed", return_value=True), \
         patch.object(handler, "_change_color", new_callable=AsyncMock) as mock_change:
        await handler.handle_message("testuser", "#channel", "message")
        mock_change.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_wrong_sender(handler):
    """Test handle_message ignores messages from other users."""
    with patch.object(handler, "_maybe_handle_toggle") as mock_toggle, \
         patch.object(handler, "_maybe_handle_ccc") as mock_ccc:
        await handler.handle_message("otheruser", "#channel", "message")
        mock_toggle.assert_not_called()
        mock_ccc.assert_not_called()


# Tests for _maybe_handle_ccc validation and processing
@pytest.mark.asyncio
async def test_maybe_handle_ccc_not_ccc_command(handler):
    """Test _maybe_handle_ccc returns False for non-ccc commands."""
    result = await handler._maybe_handle_ccc("notccc", "notccc")
    assert result is False


@pytest.mark.asyncio
async def test_maybe_handle_ccc_missing_argument(handler):
    """Test _maybe_handle_ccc handles missing argument with info log."""
    with patch("src.bot.message_handler.logging.info") as mock_info:
        result = await handler._maybe_handle_ccc("ccc", "ccc")
        assert result is True
        mock_info.assert_called_once_with("ℹ️ Ignoring invalid ccc command (missing argument) user=testuser")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_invalid_argument(handler):
    """Test _maybe_handle_ccc handles invalid argument with info log."""
    with patch.object(handler, "_normalize_color_arg", return_value=None), \
         patch("src.bot.message_handler.logging.info") as mock_info:
        result = await handler._maybe_handle_ccc("ccc invalid", "ccc invalid")
        assert result is True
        mock_info.assert_called_once_with("ℹ️ Ignoring invalid ccc argument user=testuser arg=invalid")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_preset(handler):
    """Test _maybe_handle_ccc processes valid preset color."""
    with patch.object(handler, "_normalize_color_arg", return_value="red"), \
         patch.object(handler, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await handler._maybe_handle_ccc("ccc red", "ccc red")
        assert result is True
        mock_change.assert_called_once_with("red")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_valid_hex_prime_user(handler):
    """Test _maybe_handle_ccc processes valid hex for Prime user."""
    handler.use_random_colors = True
    with patch.object(handler, "_normalize_color_arg", return_value="#ff0000"), \
         patch.object(handler, "_change_color", new_callable=AsyncMock) as mock_change:
        result = await handler._maybe_handle_ccc("ccc #ff0000", "ccc #ff0000")
        assert result is True
        mock_change.assert_called_once_with("#ff0000")


@pytest.mark.asyncio
async def test_maybe_handle_ccc_hex_non_prime_user(handler):
    """Test _maybe_handle_ccc ignores hex for non-Prime user."""
    handler.use_random_colors = False
    with patch.object(handler, "_normalize_color_arg", return_value="#ff0000"), \
         patch("src.bot.message_handler.logging.info") as mock_info:
        result = await handler._maybe_handle_ccc("ccc #ff0000", "ccc #ff0000")
        assert result is True
        mock_info.assert_called_once_with("ℹ️ Ignoring hex via ccc for non-Prime user=testuser color=#ff0000")


# Tests for _normalize_color_arg normalization
def test_normalize_color_arg_empty_string(handler):
    """Test _normalize_color_arg returns None for empty string."""
    result = handler._normalize_color_arg("")
    assert result is None


def test_normalize_color_arg_whitespace_only(handler):
    """Test _normalize_color_arg returns None for whitespace only."""
    result = handler._normalize_color_arg("   ")
    assert result is None


def test_normalize_color_arg_valid_preset_lowercase(handler):
    """Test _normalize_color_arg normalizes valid preset to lowercase."""
    with patch("src.bot.message_handler.TWITCH_PRESET_COLORS", ["Red", "Blue"]):
        result = handler._normalize_color_arg("Red")
        assert result == "red"


def test_normalize_color_arg_valid_preset_uppercase(handler):
    """Test _normalize_color_arg normalizes valid preset case-insensitively."""
    with patch("src.bot.message_handler.TWITCH_PRESET_COLORS", ["red", "blue"]):
        result = handler._normalize_color_arg("RED")
        assert result == "red"


def test_normalize_color_arg_invalid_preset(handler):
    """Test _normalize_color_arg returns None for invalid preset."""
    with patch("src.bot.message_handler.TWITCH_PRESET_COLORS", ["red", "blue"]):
        result = handler._normalize_color_arg("green")
        assert result is None


def test_normalize_color_arg_hex_6_digit_no_hash(handler):
    """Test _normalize_color_arg normalizes 6-digit hex without hash."""
    result = handler._normalize_color_arg("ff0000")
    assert result == "#ff0000"


def test_normalize_color_arg_hex_6_digit_with_hash(handler):
    """Test _normalize_color_arg normalizes 6-digit hex with hash."""
    result = handler._normalize_color_arg("#ff0000")
    assert result == "#ff0000"


def test_normalize_color_arg_hex_3_digit_no_hash(handler):
    """Test _normalize_color_arg expands 3-digit hex without hash."""
    result = handler._normalize_color_arg("abc")
    assert result == "#aabbcc"


def test_normalize_color_arg_hex_3_digit_with_hash(handler):
    """Test _normalize_color_arg expands 3-digit hex with hash."""
    result = handler._normalize_color_arg("#abc")
    assert result == "#aabbcc"


def test_normalize_color_arg_invalid_hex_length(handler):
    """Test _normalize_color_arg returns None for invalid hex length."""
    result = handler._normalize_color_arg("ff00")
    assert result is None


def test_normalize_color_arg_invalid_hex_chars(handler):
    """Test _normalize_color_arg returns None for invalid hex characters."""
    result = handler._normalize_color_arg("gggggg")
    assert result is None


def test_normalize_color_arg_hex_uppercase(handler):
    """Test _normalize_color_arg handles uppercase hex."""
    result = handler._normalize_color_arg("FF0000")
    assert result == "#ff0000"


def test_normalize_color_arg_hex_mixed_case(handler):
    """Test _normalize_color_arg handles mixed case hex."""
    result = handler._normalize_color_arg("AbCdEf")
    assert result == "#abcdef"


@pytest.mark.asyncio
async def test_maybe_handle_toggle_enable_disable(handler):
    """Test _maybe_handle_toggle for enable, disable, redundant, and invalid commands."""
    # Test enable when disabled
    handler.enabled = False
    with patch.object(handler, "_persist_enabled_flag") as mock_persist:
        result = await handler._maybe_handle_toggle("cce")
        assert result is True
        mock_persist.assert_called_once_with(True)

    # Test disable when enabled
    handler.enabled = True
    with patch.object(handler, "_persist_enabled_flag") as mock_persist:
        result = await handler._maybe_handle_toggle("ccd")
        assert result is True
        mock_persist.assert_called_once_with(False)

    # Test redundant enable
    handler.enabled = True
    with patch.object(handler, "_persist_enabled_flag") as mock_persist:
        result = await handler._maybe_handle_toggle("cce")
        assert result is True
        mock_persist.assert_not_called()

    # Test invalid
    result = await handler._maybe_handle_toggle("invalid")
    assert result is False


@pytest.mark.asyncio
async def test_persist_enabled_flag_success_and_exception(handler):
    """Test _persist_enabled_flag for success and exception cases."""
    temp_file = await asyncio.to_thread(tempfile.NamedTemporaryFile, suffix='.json', delete=False)
    try:
        handler.config_file = temp_file.name
        # Success
        with patch("src.bot.message_handler.queue_user_update") as mock_queue:
            await handler._persist_enabled_flag(True)
            mock_queue.assert_called_once()

        # Exception
        with patch("src.bot.message_handler.queue_user_update", side_effect=Exception("Test")) as mock_queue, \
             patch("src.bot.message_handler.logging.warning") as mock_warning:
            await handler._persist_enabled_flag(True)
            mock_warning.assert_called_once()
    finally:
        temp_file.close()
        await asyncio.to_thread(os.unlink, temp_file.name)


def test_is_color_change_allowed_true_false(handler):
    """Test _is_color_change_allowed when enabled is True and False."""
    # True
    handler.enabled = True
    result = handler._is_color_change_allowed()
    assert result is True

    # False
    handler.enabled = False
    result = handler._is_color_change_allowed()
    assert result is False
