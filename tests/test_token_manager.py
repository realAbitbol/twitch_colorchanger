"""Tests for EventSub TokenManager.

This module provides comprehensive tests for the TokenManager class used in EventSub chat operations.
Tests cover token validation, scope management, refresh operations, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.twitch import TwitchAPI
from src.auth_token.manager import TokenManager as GlobalTokenManager
from src.chat.token_manager import TokenManager
from src.errors.eventsub import AuthenticationError, EventSubError


class TestTokenManager:
    """Test suite for TokenManager."""

    @pytest.fixture
    def mock_session(self):
        """Mock aiohttp ClientSession."""
        return MagicMock()

    @pytest.fixture
    def mock_global_token_manager(self):
        """Mock global TokenManager."""
        manager = MagicMock(spec=GlobalTokenManager)
        manager.ensure_fresh = AsyncMock()
        manager.get_info = AsyncMock()
        return manager

    @pytest.fixture
    def mock_twitch_api(self):
        """Mock TwitchAPI."""
        api = MagicMock(spec=TwitchAPI)
        api.validate_token = AsyncMock()
        return api

    @pytest.fixture
    def token_manager(self, mock_session, mock_global_token_manager, mock_twitch_api):
        """Create TokenManager instance with mocked dependencies."""
        with patch('src.chat.token_manager.TwitchAPI', return_value=mock_twitch_api), \
             patch('src.chat.token_manager.GlobalTokenManager', return_value=mock_global_token_manager):
            return TokenManager(
                username="testuser",
                client_id="test_client_id",
                client_secret="test_secret",
                http_session=mock_session,
                token_manager=mock_global_token_manager
            )

    def test_init_valid_params(self, mock_session, mock_global_token_manager):
        """Test TokenManager initialization with valid parameters."""
        with patch('src.chat.token_manager.TwitchAPI'), \
             patch('src.chat.token_manager.GlobalTokenManager', return_value=mock_global_token_manager):
            tm = TokenManager(
                username="testuser",
                client_id="test_client_id",
                client_secret="test_secret",
                http_session=mock_session
            )

            assert tm.username == "testuser"
            assert tm.client_id == "test_client_id"
            assert tm.client_secret == "test_secret"
            assert tm.http_session == mock_session
            assert tm.recorded_scopes == set()
            assert tm.consecutive_401_count == 0
            assert tm.invalid_callback is None

    def test_init_invalid_username(self, mock_session):
        """Test TokenManager initialization with invalid username."""
        with pytest.raises(ValueError, match="username must be a non-empty string"):
            TokenManager(
                username="",
                client_id="test_client_id",
                client_secret="test_secret",
                http_session=mock_session
            )

    def test_init_invalid_client_id(self, mock_session):
        """Test TokenManager initialization with invalid client_id."""
        with pytest.raises(ValueError, match="client_id must be a non-empty string"):
            TokenManager(
                username="testuser",
                client_id=None,
                client_secret="test_secret",
                http_session=mock_session
            )

    def test_init_invalid_client_secret(self, mock_session):
        """Test TokenManager initialization with invalid client_secret."""
        with pytest.raises(ValueError, match="client_secret must be a non-empty string"):
            TokenManager(
                username="testuser",
                client_id="test_client_id",
                client_secret="",
                http_session=mock_session
            )

    def test_init_invalid_http_session(self):
        """Test TokenManager initialization with invalid http_session."""
        with pytest.raises(ValueError, match="http_session cannot be None"):
            TokenManager(
                username="testuser",
                client_id="test_client_id",
                client_secret="test_secret",
                http_session=None
            )

    @pytest.mark.asyncio
    async def test_validate_token_success(self, token_manager, mock_twitch_api):
        """Test successful token validation."""
        mock_twitch_api.validate_token.return_value = {
            "scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]
        }

        result = await token_manager.validate_token("test_token")

        assert result is True
        assert token_manager.recorded_scopes == {"chat:read", "user:read:chat", "user:manage:chat_color"}
        mock_twitch_api.validate_token.assert_called_once_with("test_token")

    @pytest.mark.asyncio
    async def test_validate_token_empty_token(self, token_manager):
        """Test token validation with empty token."""
        result = await token_manager.validate_token("")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_token_invalid_response(self, token_manager, mock_twitch_api):
        """Test token validation with invalid API response."""
        mock_twitch_api.validate_token.return_value = "invalid"

        result = await token_manager.validate_token("test_token")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_token_no_scopes(self, token_manager, mock_twitch_api):
        """Test token validation with no scopes in response."""
        mock_twitch_api.validate_token.return_value = {"client_id": "test"}

        result = await token_manager.validate_token("test_token")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_token_network_error(self, token_manager, mock_twitch_api):
        """Test token validation with network error."""
        mock_twitch_api.validate_token.side_effect = Exception("Network error")

        with pytest.raises(EventSubError, match="Token validation error"):
            await token_manager.validate_token("test_token")

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, token_manager, mock_global_token_manager):
        """Test successful token refresh."""
        # Set initial counter
        token_manager.consecutive_401_count = 3

        # Mock successful refresh
        mock_global_token_manager.ensure_fresh.return_value.name = "SUCCESS"
        mock_global_token_manager.get_info.return_value = MagicMock(
            access_token="new_token",
            refresh_token="new_refresh"
        )

        # Mock validation
        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.refresh_token()

            assert result is True
            assert token_manager.consecutive_401_count == 0  # Should be reset
            mock_global_token_manager.ensure_fresh.assert_called_once_with("testuser", False)
            mock_global_token_manager.get_info.assert_called_once_with("testuser")
            mock_validate.assert_called_once_with("new_token")

    @pytest.mark.asyncio
    async def test_refresh_token_failed(self, token_manager, mock_global_token_manager):
        """Test token refresh with failure."""
        mock_global_token_manager.ensure_fresh.return_value.name = "FAILED"

        result = await token_manager.refresh_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_no_info(self, token_manager, mock_global_token_manager):
        """Test token refresh with no token info after refresh."""
        mock_global_token_manager.ensure_fresh.return_value.name = "SUCCESS"
        mock_global_token_manager.get_info.return_value = None

        result = await token_manager.refresh_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_no_access_token(self, token_manager, mock_global_token_manager):
        """Test token refresh with no access token after refresh."""
        mock_global_token_manager.ensure_fresh.return_value.name = "SUCCESS"
        mock_global_token_manager.get_info.return_value = MagicMock(access_token=None)

        result = await token_manager.refresh_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_validation_failed(self, token_manager, mock_global_token_manager):
        """Test token refresh with validation failure."""
        mock_global_token_manager.ensure_fresh.return_value.name = "SUCCESS"
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="new_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await token_manager.refresh_token()

            assert result is False

    def test_check_scopes_success(self, token_manager):
        """Test successful scope checking."""
        token_manager.recorded_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

        result = token_manager.check_scopes()

        assert result is True

    def test_check_scopes_missing(self, token_manager):
        """Test scope checking with missing scopes."""
        token_manager.recorded_scopes = {"chat:read"}

        result = token_manager.check_scopes()

        assert result is False

    def test_set_invalid_callback(self, token_manager):
        """Test setting invalid callback."""
        callback = AsyncMock()

        token_manager.set_invalid_callback(callback)

        assert token_manager.invalid_callback == callback

    @pytest.mark.asyncio
    async def test_handle_401_error_below_threshold(self, token_manager):
        """Test 401 error handling below threshold."""
        token_manager.consecutive_401_count = 0  # Below threshold

        await token_manager.handle_401_error()

        assert token_manager.consecutive_401_count == 1

    @pytest.mark.asyncio
    async def test_handle_401_error_at_threshold(self, token_manager):
        """Test 401 error handling at threshold."""
        token_manager.consecutive_401_count = 4  # One below threshold
        callback = AsyncMock()
        token_manager.set_invalid_callback(callback)

        with pytest.raises(AuthenticationError, match="Token invalidated"):
            await token_manager.handle_401_error()

        assert token_manager.consecutive_401_count == 0
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_401_error_callback_exception(self, token_manager):
        """Test 401 error handling with callback exception."""
        token_manager.consecutive_401_count = 4
        callback = AsyncMock(side_effect=Exception("Callback error"))
        token_manager.set_invalid_callback(callback)

        with pytest.raises(AuthenticationError):
            await token_manager.handle_401_error()

        # Callback was called but exception was caught
        callback.assert_called_once()

    def test_get_scopes(self, token_manager):
        """Test getting recorded scopes."""
        token_manager.recorded_scopes = {"scope1", "scope2"}

        scopes = token_manager.get_scopes()

        assert scopes == {"scope1", "scope2"}
        assert scopes is not token_manager.recorded_scopes  # Should be a copy

    @pytest.mark.asyncio
    async def test_is_token_valid_success(self, token_manager, mock_global_token_manager):
        """Test token validity check success."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            token_manager.recorded_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

            result = await token_manager.is_token_valid()

            assert result is True
            mock_validate.assert_called_once_with("test_token")

    @pytest.mark.asyncio
    async def test_is_token_valid_no_info(self, token_manager, mock_global_token_manager):
        """Test token validity check with no token info."""
        mock_global_token_manager.get_info.return_value = None

        result = await token_manager.is_token_valid()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_no_access_token(self, token_manager, mock_global_token_manager):
        """Test token validity check with no access token."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token=None)

        result = await token_manager.is_token_valid()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_validation_failed(self, token_manager, mock_global_token_manager):
        """Test token validity check with validation failure."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await token_manager.is_token_valid()

            assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_scopes_missing(self, token_manager, mock_global_token_manager):
        """Test token validity check with missing scopes."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            token_manager.recorded_scopes = {"chat:read"}  # Missing required scopes

            result = await token_manager.is_token_valid()

            assert result is False

    def test_reset_401_counter(self, token_manager):
        """Test resetting 401 counter."""
        token_manager.consecutive_401_count = 5

        token_manager.reset_401_counter()

        assert token_manager.consecutive_401_count == 0

    def test_reset_401_counter_zero(self, token_manager):
        """Test resetting 401 counter when already zero."""
        token_manager.consecutive_401_count = 0

        token_manager.reset_401_counter()

        assert token_manager.consecutive_401_count == 0

    @pytest.mark.asyncio
    async def test_ensure_valid_token_success(self, token_manager):
        """Test ensuring valid token when already valid."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
             patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh, \
             patch.object(token_manager.token_manager, 'get_info') as mock_get_info:

            mock_is_valid.return_value = True
            mock_get_info.return_value = MagicMock(access_token="test_token")

            result = await token_manager.ensure_valid_token()

            assert result == "test_token"
            mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refresh_success(self, token_manager):
        """Test ensuring valid token with successful refresh."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
             patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh, \
             patch.object(token_manager.token_manager, 'get_info') as mock_get_info:

            mock_is_valid.side_effect = [False, True]  # First call fails, second succeeds
            mock_refresh.return_value = True
            mock_get_info.return_value = MagicMock(access_token="refreshed_token")

            result = await token_manager.ensure_valid_token()

            assert result == "refreshed_token"
            mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refresh_failed(self, token_manager):
        """Test ensuring valid token with failed refresh."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
             patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh:

            mock_is_valid.return_value = False
            mock_refresh.return_value = False

            result = await token_manager.ensure_valid_token()

            assert result is None

    @pytest.mark.asyncio
    async def test_ensure_valid_token_no_token_after_refresh(self, token_manager):
        """Test ensuring valid token with no token after refresh."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
             patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh, \
             patch.object(token_manager.token_manager, 'get_info') as mock_get_info:

            mock_is_valid.side_effect = [False, True]
            mock_refresh.return_value = True
            mock_get_info.return_value = None

            result = await token_manager.ensure_valid_token()

            assert result is None
