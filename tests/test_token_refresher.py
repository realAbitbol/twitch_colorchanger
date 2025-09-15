from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.token_refresher import TokenRefresher


class MockTokenRefresher(TokenRefresher):
    def __init__(self):
        self.username = "testuser"
        self.access_token = "oauth:token"
        self.refresh_token = "refresh"
        self.client_id = "client_id"
        self.client_secret = "client_secret"
        self.token_expiry = datetime.now()
        self.context = MagicMock()
        self.context.session = MagicMock()
        self.context.token_manager = MagicMock()
        self.context.token_manager.ensure_fresh = AsyncMock()
        self.context.token_manager.get_info = AsyncMock()
        self.context.token_manager._upsert_token_info = AsyncMock()
        self.chat_backend = MagicMock()
        self.channels = ["#chan1", "#chan2"]
        self.config_file = None
        self.use_random_colors = True
        self.token_manager = None


@pytest.fixture
def token_refresher():
    return MockTokenRefresher()


@pytest.mark.asyncio
async def test_check_and_refresh_token_force_refresh_failure(token_refresher):
    """Test _check_and_refresh_token with force refresh failure."""
    token_refresher.token_manager = MagicMock()
    token_refresher.token_manager.ensure_fresh = AsyncMock(return_value=MagicMock(name="FAILED"))
    token_refresher.token_manager.get_info = AsyncMock(return_value=None)

    result = await token_refresher._check_and_refresh_token(force=True)
    assert result is False


@pytest.mark.asyncio
async def test_persist_token_changes_config_save_failure(token_refresher):
    """Test _persist_token_changes with config save failure."""
    token_refresher.config_file = "test.json"
    with patch.object(token_refresher, "_validate_config_prerequisites", return_value=True), \
         patch.object(token_refresher, "_build_user_config", return_value={}), \
         patch.object(token_refresher, "_attempt_config_save", return_value=False):
        await token_refresher._persist_token_changes()


@pytest.mark.asyncio
async def test_attempt_config_save_retry_exhaustion(token_refresher):
    """Test _attempt_config_save with retry exhaustion."""
    token_refresher.config_file = "test.json"
    user_config = {}
    with patch("src.bot.token_refresher.async_update_user_in_config", side_effect=RuntimeError("Save failed")), \
         patch("src.bot.token_refresher.logging") as mock_logging:
        result = await token_refresher._attempt_config_save(user_config, 2, 3)
        assert result is True
        mock_logging.error.assert_called()


@pytest.mark.asyncio
async def test_handle_config_save_error_permission_denied(token_refresher):
    """Test _handle_config_save_error with permission denied."""
    error = OSError("Permission denied")
    with patch("src.bot.token_refresher.logging") as mock_logging:
        result = await token_refresher._handle_config_save_error(error, 0, 3)
        assert result is False
        mock_logging.warning.assert_called()


@pytest.mark.asyncio
async def test_validate_config_prerequisites_missing_file(token_refresher):
    """Test _validate_config_prerequisites with missing file."""
    token_refresher.config_file = None
    result = token_refresher._validate_config_prerequisites()
    assert result is False


@pytest.mark.asyncio
async def test_setup_token_manager_registration_failure(token_refresher):
    """Test _setup_token_manager with registration failure."""
    token_refresher.context.token_manager = None
    result = await token_refresher._setup_token_manager()
    assert result is False


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_persist_failure(token_refresher):
    """Test _normalize_channels_if_needed with persist failure."""
    token_refresher.channels = ["#chan1"]
    with patch("src.config.model.normalize_channels_list", return_value=(["#chan1"], True)), \
         patch.object(token_refresher, "_persist_normalized_channels", side_effect=OSError("Persist failed")), \
         pytest.raises(OSError):
        await token_refresher._normalize_channels_if_needed()


@pytest.mark.asyncio
async def test_setup_token_manager_success(token_refresher):
    """Test _setup_token_manager success."""
    result = await token_refresher._setup_token_manager()
    assert result is True
    token_refresher.context.token_manager._upsert_token_info.assert_called_once()


@pytest.mark.asyncio
async def test_handle_initial_token_refresh_success(token_refresher):
    """Test _handle_initial_token_refresh success."""
    token_refresher.token_manager = token_refresher.context.token_manager
    token_refresher.context.token_manager.ensure_fresh.return_value = MagicMock()
    token_refresher.context.token_manager.get_info.return_value = MagicMock(access_token="new_token", refresh_token="new_refresh", expiry=None)
    await token_refresher._handle_initial_token_refresh()
    assert token_refresher.access_token == "new_token"


@pytest.mark.asyncio
async def test_handle_initial_token_refresh_no_change(token_refresher):
    """Test _handle_initial_token_refresh with no change."""
    token_refresher.token_manager = token_refresher.context.token_manager
    token_refresher.context.token_manager.ensure_fresh.return_value = None
    await token_refresher._handle_initial_token_refresh()
    assert token_refresher.access_token == "oauth:token"


@pytest.mark.asyncio
async def test_log_scopes_if_possible_success(token_refresher):
    """Test _log_scopes_if_possible success."""
    with patch("src.bot.token_refresher.TwitchAPI") as mock_api, \
         patch("src.bot.token_refresher.handle_api_error") as mock_handle:
        mock_api.return_value.validate_token.return_value = {"scopes": ["chat:read"]}
        mock_handle.return_value = {"scopes": ["chat:read"]}
        await token_refresher._log_scopes_if_possible()
        mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_log_scopes_if_possible_no_session(token_refresher):
    """Test _log_scopes_if_possible with no session."""
    token_refresher.context.session = None
    await token_refresher._log_scopes_if_possible()
    # No assertions needed, just ensure no exception


@pytest.mark.asyncio
async def test_log_scopes_if_possible_validation_error(token_refresher):
    """Test _log_scopes_if_possible with validation error."""
    with patch("src.bot.token_refresher.TwitchAPI"), \
         patch("src.bot.token_refresher.handle_api_error", side_effect=ValueError("Validation error")):
        await token_refresher._log_scopes_if_possible()
        # No assertions needed, just ensure no exception


@pytest.mark.asyncio
async def test_normalize_channels_if_needed_no_change(token_refresher):
    """Test _normalize_channels_if_needed with no change."""
    token_refresher.channels = ["chan1"]
    with patch("src.config.model.normalize_channels_list", return_value=(["chan1"], False)):
        result = await token_refresher._normalize_channels_if_needed()
        assert result == ["chan1"]


@pytest.mark.asyncio
async def test_check_and_refresh_token_success(token_refresher):
    """Test _check_and_refresh_token success."""
    token_refresher.token_manager = token_refresher.context.token_manager
    token_refresher.context.token_manager.ensure_fresh.return_value = MagicMock(name="VALID")
    token_refresher.context.token_manager.get_info.return_value = MagicMock(access_token="new_token")
    result = await token_refresher._check_and_refresh_token()
    assert result is True


@pytest.mark.asyncio
async def test_check_and_refresh_token_no_token_manager(token_refresher):
    """Test _check_and_refresh_token with no token manager."""
    token_refresher.token_manager = None
    token_refresher.context.token_manager = None
    result = await token_refresher._check_and_refresh_token()
    assert result is False


@pytest.mark.asyncio
async def test_persist_token_changes_success(token_refresher):
    """Test _persist_token_changes success."""
    token_refresher.config_file = "test.json"
    with patch.object(token_refresher, "_validate_config_prerequisites", return_value=True), \
         patch.object(token_refresher, "_build_user_config", return_value={}), \
         patch.object(token_refresher, "_attempt_config_save", return_value=True):
        await token_refresher._persist_token_changes()


@pytest.mark.asyncio
async def test_persist_normalized_channels_success(token_refresher):
    """Test _persist_normalized_channels success."""
    token_refresher.config_file = "test.json"
    with patch.object(token_refresher, "_build_user_config", return_value={"channels": ["#chan1"]}), \
         patch("src.bot.token_refresher.queue_user_update"):
        await token_refresher._persist_normalized_channels()


@pytest.mark.asyncio
async def test_persist_normalized_channels_no_config(token_refresher):
    """Test _persist_normalized_channels with no config."""
    token_refresher.config_file = None
    await token_refresher._persist_normalized_channels()
    # No assertions needed, just ensure no exception


@pytest.mark.asyncio
async def test_validate_config_prerequisites_missing_access_token(token_refresher):
    """Test _validate_config_prerequisites with missing access token."""
    token_refresher.config_file = "test.json"
    token_refresher.access_token = None
    result = token_refresher._validate_config_prerequisites()
    assert result is False


@pytest.mark.asyncio
async def test_validate_config_prerequisites_missing_refresh_token(token_refresher):
    """Test _validate_config_prerequisites with missing refresh token."""
    token_refresher.config_file = "test.json"
    token_refresher.refresh_token = None
    result = token_refresher._validate_config_prerequisites()
    assert result is False


@pytest.mark.asyncio
async def test_build_user_config(token_refresher):
    """Test _build_user_config."""
    result = token_refresher._build_user_config()
    assert result["username"] == "testuser"
    assert result["access_token"] == "oauth:token"


@pytest.mark.asyncio
async def test_attempt_config_save_success(token_refresher):
    """Test _attempt_config_save success."""
    token_refresher.config_file = "test.json"
    with patch("src.bot.token_refresher.async_update_user_in_config", return_value=True):
        result = await token_refresher._attempt_config_save({}, 0, 3)
        assert result is True


@pytest.mark.asyncio
async def test_attempt_config_save_file_not_found(token_refresher):
    """Test _attempt_config_save with file not found."""
    token_refresher.config_file = "test.json"
    with patch("src.bot.token_refresher.async_update_user_in_config", side_effect=FileNotFoundError):
        result = await token_refresher._attempt_config_save({}, 0, 3)
        assert result is True


@pytest.mark.asyncio
async def test_handle_config_save_error_retry(token_refresher):
    """Test _handle_config_save_error with retry."""
    error = RuntimeError("Save failed")
    result = await token_refresher._handle_config_save_error(error, 0, 3)
    assert result is False


@pytest.mark.asyncio
async def test_handle_config_save_error_final_failure(token_refresher):
    """Test _handle_config_save_error with final failure."""
    error = RuntimeError("Save failed")
    result = await token_refresher._handle_config_save_error(error, 2, 3)
    assert result is True
