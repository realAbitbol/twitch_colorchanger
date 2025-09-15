from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.core import TwitchColorBot
from src.bot.token_handler import TokenHandler


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.token_manager = MagicMock()
    ctx.token_manager.ensure_fresh = AsyncMock()
    ctx.token_manager.get_info = AsyncMock()
    return ctx


@pytest.fixture
def mock_http_session():
    return MagicMock()


@pytest.fixture
def bot(mock_context, mock_http_session):
    return TwitchColorBot(
        context=mock_context,
        token="oauth:token",
        refresh_token="refresh",
        client_id="client_id",
        client_secret="client_secret",
        nick="testuser",
        channels=["#chan1", "#chan2"],
        http_session=mock_http_session,
        is_prime_or_turbo=True,
        config_file=None,
        user_id="123",
        enabled=True,
    )


@pytest.fixture
def token_handler(bot):
    return TokenHandler(bot)


@pytest.mark.asyncio
async def test_check_and_refresh_token_force_refresh_failure(token_handler, bot):
    """Test check_and_refresh_token with force refresh failure."""
    bot.token_manager = MagicMock()
    bot.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="FAILED"))
    bot.token_manager.get_info = AsyncMock(return_value=None)

    result = await token_handler.check_and_refresh_token(force=True)
    assert result is False


@pytest.mark.asyncio
async def test_check_and_refresh_token_backend_update_failure(token_handler, bot):
    """Test check_and_refresh_token with backend update failure."""
    bot.token_manager = MagicMock()
    bot.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="SUCCESS"))
    info = MagicMock()
    info.access_token = "new_token"
    bot.token_manager.get_info = AsyncMock(return_value=info)
    bot.connection_manager.chat_backend = MagicMock()
    bot.connection_manager.chat_backend.update_token = MagicMock(side_effect=ValueError("Update failed"))

    with patch("src.bot.token_handler.logging") as mock_logging:
        result = await token_handler.check_and_refresh_token()
        assert result is True
        mock_logging.debug.assert_called()


@pytest.mark.asyncio
async def test_persist_token_changes_config_save_failure(token_handler, bot):
    """Test _persist_token_changes with config save failure."""
    bot.config_file = "test.json"
    with patch.object(token_handler, "_validate_config_prerequisites", return_value=True), \
         patch.object(token_handler, "_build_user_config", return_value={}), \
         patch.object(token_handler, "_attempt_config_save", return_value=False):
        await token_handler._persist_token_changes()


@pytest.mark.asyncio
async def test_attempt_config_save_retry_exhaustion(token_handler, bot):
    """Test _attempt_config_save with retry exhaustion."""
    bot.config_file = "test.json"
    user_config = {}
    with patch("src.bot.token_handler.async_update_user_in_config", side_effect=RuntimeError("Save failed")), \
         patch("src.bot.token_handler.logging") as mock_logging:
        result = await token_handler._attempt_config_save(user_config, 2, 3)
        assert result is True
        mock_logging.error.assert_called()


@pytest.mark.asyncio
async def test_handle_config_save_error_permission_denied(token_handler, bot):
    """Test _handle_config_save_error with permission denied."""
    error = OSError("Permission denied")
    with patch("src.bot.token_handler.logging") as mock_logging:
        result = await token_handler._handle_config_save_error(error, 0, 3)
        assert result is False
        mock_logging.warning.assert_called()


@pytest.mark.asyncio
async def test_validate_config_prerequisites_missing_file(token_handler, bot):
    """Test _validate_config_prerequisites with missing file."""
    bot.config_file = None
    result = token_handler._validate_config_prerequisites()
    assert result is False


@pytest.mark.asyncio
async def test_setup_token_manager_registration_failure(token_handler, bot):
    """Test setup_token_manager with registration failure."""
    bot.context.token_manager = None
    result = await token_handler.setup_token_manager()
    assert result is False


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_persist_failure(token_handler, bot):
    """Test normalize_channels_if_needed with persist failure."""
    bot.channels = ["#chan1"]
    with patch("src.config.model.normalize_channels_list", return_value=(["#chan1"], True)), \
         patch.object(token_handler, "_persist_normalized_channels", side_effect=OSError("Persist failed")), \
         pytest.raises(OSError):
        await token_handler.normalize_channels_if_needed()


@pytest.mark.asyncio
async def test_setup_token_manager_success(token_handler, bot):
    """Test setup_token_manager with successful setup."""
    bot.context.token_manager = MagicMock()
    bot.context.token_manager._upsert_token_info = AsyncMock()
    bot.context.token_manager.register_update_hook = MagicMock()
    result = await token_handler.setup_token_manager()
    assert result is True
    assert bot.token_manager == bot.context.token_manager


@pytest.mark.asyncio
async def test_handle_initial_token_refresh_success(token_handler, bot):
    """Test handle_initial_token_refresh with successful refresh."""
    bot.token_manager = MagicMock()
    bot.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="SUCCESS"))
    info = MagicMock()
    info.access_token = "new_token"
    info.refresh_token = "new_refresh"
    info.expiry = "expiry"
    bot.token_manager.get_info = AsyncMock(return_value=info)
    bot.access_token = "old_token"
    bot.refresh_token = "old_refresh"
    with patch.object(token_handler, "_persist_token_changes", new_callable=AsyncMock):
        await token_handler.handle_initial_token_refresh()
        assert bot.access_token == "new_token"
        assert bot.refresh_token == "new_refresh"
        assert bot.token_expiry == "expiry"


@pytest.mark.asyncio
async def test_handle_initial_token_refresh_no_change(token_handler, bot):
    """Test handle_initial_token_refresh with no token changes."""
    bot.token_manager = MagicMock()
    bot.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="SUCCESS"))
    info = MagicMock()
    info.access_token = "same_token"
    info.refresh_token = "same_refresh"
    info.expiry = "same_expiry"
    bot.token_manager.get_info = AsyncMock(return_value=info)
    bot.access_token = "same_token"
    bot.refresh_token = "same_refresh"
    with patch.object(token_handler, "_persist_token_changes", new_callable=AsyncMock) as mock_persist:
        await token_handler.handle_initial_token_refresh()
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_success(token_handler, bot):
    """Test log_scopes_if_possible with successful validation."""
    bot.context.session = MagicMock()
    api_mock = MagicMock()
    api_mock.validate_token = AsyncMock(return_value={"scopes": ["chat:read", "user:read"]})
    with patch("src.bot.token_handler.TwitchAPI", return_value=api_mock), \
         patch("src.bot.token_handler.handle_api_error", new_callable=AsyncMock, return_value={"scopes": ["chat:read", "user:read"]}), \
         patch("src.bot.token_handler.logging") as mock_logging:
        await token_handler.log_scopes_if_possible()
        mock_logging.info.assert_called()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_no_session(token_handler, bot):
    """Test log_scopes_if_possible with no session."""
    bot.context.session = None
    with patch("src.bot.token_handler.logging") as mock_logging:
        await token_handler.log_scopes_if_possible()
        mock_logging.info.assert_not_called()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_validation_error(token_handler, bot):
    """Test log_scopes_if_possible with validation error."""
    bot.context.session = MagicMock()
    api_mock = MagicMock()
    api_mock.validate_token = AsyncMock(side_effect=ValueError("Validation error"))
    with patch("src.bot.token_handler.TwitchAPI", return_value=api_mock), \
         patch("src.bot.token_handler.handle_api_error", new_callable=AsyncMock, side_effect=ValueError("Validation error")), \
         patch("src.bot.token_handler.logging") as mock_logging:
        await token_handler.log_scopes_if_possible()
        mock_logging.debug.assert_called()


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_no_change(token_handler, bot):
    """Test normalize_channels_if_needed with no changes needed."""
    bot.channels = ["chan1"]
    with patch("src.config.model.normalize_channels_list", return_value=(["chan1"], False)), \
         patch.object(token_handler, "_persist_normalized_channels", new_callable=AsyncMock) as mock_persist:
        result = await token_handler.normalize_channels_if_needed()
        assert result == ["chan1"]
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_refresh_token_success(token_handler, bot):
    """Test check_and_refresh_token with successful refresh."""
    bot.token_manager = MagicMock()
    bot.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="SUCCESS"))
    info = MagicMock()
    info.access_token = "new_token"
    info.expiry = "expiry"
    bot.token_manager.get_info = AsyncMock(return_value=info)
    bot.access_token = "old_token"
    bot.connection_manager.chat_backend = MagicMock()
    bot.connection_manager.chat_backend.update_token = MagicMock()
    result = await token_handler.check_and_refresh_token()
    assert result is True
    assert bot.access_token == "new_token"
    assert bot.token_expiry == "expiry"


@pytest.mark.asyncio
async def test_check_and_refresh_token_no_token_manager(token_handler, bot):
    """Test check_and_refresh_token with no token manager."""
    bot.token_manager = None
    bot.context.token_manager = None
    result = await token_handler.check_and_refresh_token()
    assert result is False


@pytest.mark.asyncio
async def test_persist_token_changes_success(token_handler, bot):
    """Test _persist_token_changes with successful persistence."""
    bot.config_file = "test.json"
    with patch.object(token_handler, "_validate_config_prerequisites", return_value=True), \
         patch.object(token_handler, "_build_user_config", return_value={}), \
         patch.object(token_handler, "_attempt_config_save", new_callable=AsyncMock, return_value=True):
        await token_handler._persist_token_changes()


@pytest.mark.asyncio
async def test_persist_normalized_channels_success(token_handler, bot):
    """Test _persist_normalized_channels with successful persistence."""
    bot.config_file = "test.json"
    with patch("src.bot.token_handler.queue_user_update", new_callable=AsyncMock):
        await token_handler._persist_normalized_channels()


@pytest.mark.asyncio
async def test_persist_normalized_channels_no_config(token_handler, bot):
    """Test _persist_normalized_channels with no config file."""
    bot.config_file = None
    with patch("src.bot.token_handler.queue_user_update", new_callable=AsyncMock) as mock_queue:
        await token_handler._persist_normalized_channels()
        mock_queue.assert_not_called()


def test_validate_config_prerequisites_missing_access_token(token_handler, bot):
    """Test _validate_config_prerequisites with missing access token."""
    bot.config_file = "test.json"
    bot.access_token = None
    result = token_handler._validate_config_prerequisites()
    assert result is False


def test_validate_config_prerequisites_missing_refresh_token(token_handler, bot):
    """Test _validate_config_prerequisites with missing refresh token."""
    bot.config_file = "test.json"
    bot.access_token = "token"
    bot.refresh_token = None
    result = token_handler._validate_config_prerequisites()
    assert result is False


def test_build_user_config(token_handler, bot):
    """Test _build_user_config builds correct config dict."""
    bot.username = "testuser"
    bot.channels = ["#chan1"]
    bot.client_id = "client"
    bot.client_secret = "secret"
    bot.access_token = "access"
    bot.refresh_token = "refresh"
    bot.token_expiry = "expiry"
    bot.use_random_colors = True
    bot.enabled = True
    config = token_handler._build_user_config()
    expected = {
        "username": "testuser",
        "client_id": "client",
        "client_secret": "secret",
        "access_token": "access",
        "refresh_token": "refresh",
        "token_expiry": "expiry",
        "channels": ["#chan1"],
        "is_prime_or_turbo": True,
        "enabled": True,
    }
    assert config == expected


@pytest.mark.asyncio
async def test_attempt_config_save_success(token_handler, bot):
    """Test _attempt_config_save with successful save."""
    bot.config_file = "test.json"
    user_config = {}
    with patch("src.bot.token_handler.async_update_user_in_config", new_callable=AsyncMock, return_value=True):
        result = await token_handler._attempt_config_save(user_config, 0, 3)
        assert result is True


@pytest.mark.asyncio
async def test_attempt_config_save_file_not_found(token_handler, bot):
    """Test _attempt_config_save with file not found."""
    bot.config_file = "test.json"
    user_config = {}
    with patch("src.bot.token_handler.async_update_user_in_config", side_effect=FileNotFoundError("Not found")):
        result = await token_handler._attempt_config_save(user_config, 0, 3)
        assert result is True


@pytest.mark.asyncio
async def test_handle_config_save_error_retry(token_handler, bot):
    """Test _handle_config_save_error with retry."""
    error = RuntimeError("Save failed")
    with patch("src.bot.token_handler.logging") as mock_logging, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result = await token_handler._handle_config_save_error(error, 0, 3)
        assert result is False
        mock_logging.warning.assert_called()


@pytest.mark.asyncio
async def test_handle_config_save_error_final_failure(token_handler, bot):
    """Test _handle_config_save_error with final failure."""
    error = RuntimeError("Save failed")
    with patch("src.bot.token_handler.logging") as mock_logging, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result = await token_handler._handle_config_save_error(error, 2, 3)
        assert result is True
        mock_logging.error.assert_called()
