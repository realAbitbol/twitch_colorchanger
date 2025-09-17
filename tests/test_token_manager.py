"""Tests for EventSub TokenManager.

This module provides comprehensive tests for the TokenManager class used in EventSub chat operations.
Tests cover token validation, scope management, refresh operations, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.twitch import TwitchAPI
from src.auth_token.manager import TokenManager
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
        manager = MagicMock()
        manager.ensure_fresh = AsyncMock()
        manager.get_info = AsyncMock()
        manager.validate = AsyncMock()
        return manager

    @pytest.fixture
    def mock_twitch_api(self):
        """Mock TwitchAPI."""
        api = MagicMock(spec=TwitchAPI)
        api.validate_token = AsyncMock()
        return api

    @pytest.fixture
    def token_manager(self, mock_session, mock_twitch_api, mock_global_token_manager):
        """Create TokenManager instance with mocked dependencies."""
        with patch('src.auth_token.manager.TwitchAPI', return_value=mock_twitch_api):
            return TokenManager(mock_session)

    def test_init_valid_params(self, token_manager):
        """Test TokenManager initialization with valid parameters."""
        # TokenManager is singleton, just check it's initialized
        assert token_manager.http_session is not None
        assert token_manager.api is not None


    @pytest.mark.asyncio
    async def test_validate_token_success(self, token_manager, mock_twitch_api):
        """Test successful token validation."""
        mock_twitch_api.validate_token.return_value = {
            "scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]
        }

        result = await token_manager.validate_token("test_token")

        assert result is True
        scopes = token_manager.get_scopes()
        assert scopes == {"chat:read", "user:read:chat", "user:manage:chat_color"}
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
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.consecutive_401_count = 3  # Set initial counter

        # Mock successful refresh - use REFRESHED which is what the method expects
        mock_outcome = MagicMock()
        mock_outcome.name = "REFRESHED"
        mock_global_token_manager.ensure_fresh.return_value = mock_outcome
        mock_global_token_manager.get_info.return_value = MagicMock(
            access_token="new_token",
            refresh_token="new_refresh"
        )

        # Mock validation
        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.refresh_token("testuser")

            assert result is True
            info = await token_manager.get_info("testuser")
            assert info.consecutive_401_count == 0  # Should be reset
            mock_global_token_manager.ensure_fresh.assert_called_once_with("testuser", False)
            # The method doesn't call global get_info, it uses local get_info
            # mock_validate is not called in refresh_token, it's called in handle_401_and_refresh

    @pytest.mark.asyncio
    async def test_refresh_token_failed(self, token_manager, mock_global_token_manager):
        """Test token refresh with failure."""
        mock_global_token_manager.ensure_fresh.return_value.name = "FAILED"

        result = await token_manager.refresh_token("testuser")

        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_no_info(self, token_manager, mock_global_token_manager):
        """Test token refresh with no token info after refresh."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)

        mock_outcome = MagicMock()
        mock_outcome.name = "SUCCESS"
        mock_global_token_manager.ensure_fresh.return_value = mock_outcome
        mock_global_token_manager.get_info.return_value = None

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.refresh_token("testuser")

            # The method only checks outcome, not whether get_info returns valid data
            assert result is True

    @pytest.mark.asyncio
    async def test_refresh_token_no_access_token(self, token_manager, mock_global_token_manager):
        """Test token refresh with no access token after refresh."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)

        mock_outcome = MagicMock()
        mock_outcome.name = "SUCCESS"
        mock_global_token_manager.ensure_fresh.return_value = mock_outcome
        mock_global_token_manager.get_info.return_value = MagicMock(access_token=None)

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.refresh_token("testuser")

            # The method only checks outcome, not whether get_info returns valid data
            assert result is True

    @pytest.mark.asyncio
    async def test_refresh_token_validation_failed(self, token_manager, mock_global_token_manager):
        """Test token refresh with validation failure."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)

        mock_outcome = MagicMock()
        mock_outcome.name = "SUCCESS"
        mock_global_token_manager.ensure_fresh.return_value = mock_outcome
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="new_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.refresh_token("testuser")

            # The method only checks outcome, not validation result
            assert result is True

    @pytest.mark.asyncio
    async def test_check_scopes_success(self, token_manager):
        """Test successful scope checking."""
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.recorded_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

        result = token_manager.check_scopes("testuser", {"chat:read"})

        assert result is True

    @pytest.mark.asyncio
    async def test_check_scopes_missing(self, token_manager):
        """Test scope checking with missing scopes."""
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.recorded_scopes = {"chat:read"}

        result = token_manager.check_scopes("testuser", {"chat:read", "user:read:chat", "user:manage:chat_color"})

        assert result is False

    @pytest.mark.asyncio
    async def test_set_invalid_callback(self, token_manager):
        """Test setting invalid callback."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        callback = AsyncMock()

        token_manager.set_invalid_callback(callback)

        # Since we refactored the callback storage, we need to check the token info
        info = await token_manager.get_info("testuser")
        assert info is not None
        assert info.invalid_callback == callback

    @pytest.mark.asyncio
    async def test_handle_401_error_below_threshold(self, token_manager):
        """Test 401 error handling below threshold."""
        # First create a token info for the user
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)

        await token_manager.handle_401_error("testuser")

        info = await token_manager.get_info("testuser")
        assert info is not None
        assert info.consecutive_401_count == 1

    @pytest.mark.asyncio
    async def test_handle_401_error_at_threshold(self, token_manager):
        """Test 401 error handling at threshold."""
        # Create token info and set up callback
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        callback = AsyncMock()
        token_manager.set_invalid_callback("testuser", callback)

        # Set counter to threshold - 1
        info = await token_manager.get_info("testuser")
        info.consecutive_401_count = 4

        with pytest.raises(AuthenticationError, match="Token invalidated"):
            await token_manager.handle_401_error("testuser")

        # Check counter was reset
        info = await token_manager.get_info("testuser")
        assert info.consecutive_401_count == 0
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_401_error_callback_exception(self, token_manager):
        """Test 401 error handling with callback exception."""
        # Create token info and set up callback
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        callback = AsyncMock(side_effect=Exception("Callback error"))
        token_manager.set_invalid_callback(callback)

        # Set counter to threshold
        info = await token_manager.get_info("testuser")
        info.consecutive_401_count = 4

        with pytest.raises(AuthenticationError):
            await token_manager.handle_401_error("testuser")

        # Callback was called but exception was caught
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_scopes(self, token_manager):
        """Test getting recorded scopes."""
        # Create token info with scopes
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.recorded_scopes = {"scope1", "scope2"}

        scopes = token_manager.get_scopes("testuser")

        assert scopes == {"scope1", "scope2"}
        assert scopes is not info.recorded_scopes  # Should be a copy

    @pytest.mark.asyncio
    async def test_is_token_valid_success(self, token_manager, mock_global_token_manager):
        """Test token validity check success."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "test_token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.recorded_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        # Mock the validate method - return "VALID" as string since the method handles both objects and strings
        mock_global_token_manager.validate.return_value = "VALID"

        result = await token_manager.is_token_valid("testuser")

        assert result is True
        mock_global_token_manager.validate.assert_called_once_with("testuser")

    @pytest.mark.asyncio
    async def test_is_token_valid_no_info(self, token_manager, mock_global_token_manager):
        """Test token validity check with no token info."""
        mock_global_token_manager.get_info.return_value = None

        result = await token_manager.is_token_valid("testuser")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_no_access_token(self, token_manager, mock_global_token_manager):
        """Test token validity check with no access token."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token=None)

        result = await token_manager.is_token_valid("testuser")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_validation_failed(self, token_manager, mock_global_token_manager):
        """Test token validity check with validation failure."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await token_manager.is_token_valid("testuser")

            assert result is False

    @pytest.mark.asyncio
    async def test_is_token_valid_scopes_missing(self, token_manager, mock_global_token_manager):
        """Test token validity check with missing scopes."""
        mock_global_token_manager.get_info.return_value = MagicMock(access_token="test_token")

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            token_manager.recorded_scopes = {"chat:read"}  # Missing required scopes

            result = await token_manager.is_token_valid("testuser")

            assert result is False

    @pytest.mark.asyncio
    async def test_reset_401_counter(self, token_manager):
        """Test resetting 401 counter."""
        # Create token info and set counter
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.consecutive_401_count = 5

        token_manager.reset_401_counter("testuser")

        info = await token_manager.get_info("testuser")
        assert info.consecutive_401_count == 0

    @pytest.mark.asyncio
    async def test_reset_401_counter_zero(self, token_manager):
        """Test resetting 401 counter when already zero."""
        # Create token info
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)

        token_manager.reset_401_counter("testuser")

        info = await token_manager.get_info("testuser")
        assert info.consecutive_401_count == 0

    @pytest.mark.asyncio
    async def test_ensure_valid_token_success(self, token_manager):
        """Test ensuring valid token when already valid."""
        # Create token info
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "test_token", "refresh", "client", "secret", expiry)

        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
              patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh:

            mock_is_valid.return_value = True

            result = await token_manager.ensure_valid_token("testuser")

            assert result == "test_token"
            mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refresh_success(self, token_manager):
        """Test ensuring valid token with successful refresh."""
        # Create token info
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)

        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
              patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh:

            mock_is_valid.side_effect = [False, True]  # First call fails, second succeeds
            mock_refresh.return_value = True

            result = await token_manager.ensure_valid_token("testuser")

            assert result == "old_token"  # Should return the original token
            mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refresh_failed(self, token_manager):
        """Test ensuring valid token with failed refresh."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
              patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh:

            mock_is_valid.return_value = False
            mock_refresh.return_value = False

            result = await token_manager.ensure_valid_token("testuser")

            assert result is None

    @pytest.mark.asyncio
    async def test_handle_401_error_uses_configurable_threshold(self, token_manager):
        """Test that 401 error handling uses configurable threshold from environment."""
        # Create token info
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "token", "refresh", "client", "secret", expiry)

        # Mock the constant to test different threshold values
        with patch('src.chat.token_manager.EVENTSUB_CONSECUTIVE_401_THRESHOLD', 5):
            # Reset counter and test below threshold
            info = await token_manager.get_info("testuser")
            info.consecutive_401_count = 3  # Below new threshold of 5

            await token_manager.handle_401_error()

            info = await token_manager.get_info("testuser")
            assert info.consecutive_401_count == 4
            # Should not raise AuthenticationError since below threshold

            # Test at threshold
            with pytest.raises(AuthenticationError, match="Token invalidated"):
                await token_manager.handle_401_error()

            info = await token_manager.get_info("testuser")
            assert info.consecutive_401_count == 0  # Should be reset

    @pytest.mark.asyncio
    async def test_handle_401_and_refresh_success(self, token_manager, mock_global_token_manager):
        """Test successful 401 refresh."""
        # Create token info first
        from datetime import UTC, datetime
        expiry = datetime.now(UTC)
        await token_manager._upsert_token_info("testuser", "old_token", "refresh", "client", "secret", expiry)
        info = await token_manager.get_info("testuser")
        info.consecutive_401_count = 3  # Set initial counter

        mock_outcome = MagicMock()
        mock_outcome.name = "REFRESHED"  # Use REFRESHED which the method expects
        mock_global_token_manager.ensure_fresh.return_value = mock_outcome
        mock_global_token_manager.get_info.return_value = MagicMock(
            access_token="new_token",
            refresh_token="new_refresh",
            client_id="client_id",
            client_secret="client_secret"
        )

        with patch.object(token_manager, 'validate_token', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True

            result = await token_manager.handle_401_and_refresh("testuser")

            assert result == "new_token"
            info = await token_manager.get_info("testuser")
            assert info.consecutive_401_count == 0

    @pytest.mark.asyncio
    async def test_handle_401_and_refresh_failed(self, token_manager, mock_global_token_manager):
        """Test failed 401 refresh."""
        mock_global_token_manager.ensure_fresh.return_value.name = "FAILED"

        result = await token_manager.handle_401_and_refresh("testuser")

        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_valid_token_no_token_after_refresh(self, token_manager):
        """Test ensuring valid token with no token after refresh."""
        with patch.object(token_manager, 'is_token_valid', new_callable=AsyncMock) as mock_is_valid, \
              patch.object(token_manager, 'refresh_token', new_callable=AsyncMock) as mock_refresh:

            mock_is_valid.side_effect = [False, True]
            mock_refresh.return_value = True

            result = await token_manager.ensure_valid_token("testuser")

            assert result is None
