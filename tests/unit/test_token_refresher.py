"""
Unit tests for TokenRefresher.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone

from src.auth_token.token_refresher import TokenRefresher
from src.auth_token.client import TokenOutcome, RefreshErrorType, TokenResult
from src.auth_token.types import TokenState


class TestTokenRefresher:
    """Test class for TokenRefresher functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_manager = Mock()
        self.mock_manager._tokens_lock = AsyncMock()
        self.refresher = TokenRefresher(self.mock_manager)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_ensure_fresh_no_token_info(self):
        """Test ensure_fresh returns FAILED when no token info exists."""
        # Arrange
        self.mock_manager.tokens = {}

        # Act
        result = await self.refresher.ensure_fresh("nonexistent_user")

        # Assert
        assert result == TokenOutcome.FAILED

    @pytest.mark.asyncio
    async def test_ensure_fresh_skip_refresh_when_fresh(self):
        """Test ensure_fresh returns VALID when token is fresh and not forced."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=2)  # Well above threshold
        self.mock_manager.tokens = {"testuser": mock_info}

        # Mock validator.remaining_seconds to return high value
        self.mock_manager.validator.remaining_seconds.return_value = 7200  # 2 hours

        # Act
        result = await self.refresher.ensure_fresh("testuser", force_refresh=False)

        # Assert
        assert result == TokenOutcome.VALID
        self.mock_manager.validator.remaining_seconds.assert_called_once_with(mock_info)

    @pytest.mark.asyncio
    async def test_ensure_fresh_force_refresh(self):
        """Test ensure_fresh performs refresh when forced."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_info.client_id = "client123"
        mock_info.client_secret = "secret123"
        self.mock_manager.tokens = {"testuser": mock_info}

        mock_client = AsyncMock()
        mock_result = TokenResult(TokenOutcome.REFRESHED, "new_token", "new_refresh", datetime.now(timezone.utc) + timedelta(hours=1))
        self.mock_manager.client_cache.get_client = AsyncMock(return_value=mock_client)

        with patch.object(self.refresher, '_refresh_with_lock', new_callable=AsyncMock) as mock_refresh:
            mock_refresh.return_value = (mock_result, True)

            # Act
            result = await self.refresher.ensure_fresh("testuser", force_refresh=True)

        # Assert
        assert result == TokenOutcome.REFRESHED
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_fresh_successful_refresh(self):
        """Test ensure_fresh performs and applies successful refresh."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(minutes=30)  # Below threshold
        mock_info.client_id = "client123"
        mock_info.client_secret = "secret123"
        self.mock_manager.tokens = {"testuser": mock_info}

        self.mock_manager.validator.remaining_seconds.return_value = 1800  # 30 minutes

        mock_client = AsyncMock()
        mock_result = TokenResult(TokenOutcome.REFRESHED, "new_token", "new_refresh", datetime.now(timezone.utc) + timedelta(hours=1))
        self.mock_manager.client_cache.get_client = AsyncMock(return_value=mock_client)

        with patch.object(self.refresher, '_refresh_with_lock', new_callable=AsyncMock) as mock_refresh:
            mock_refresh.return_value = (mock_result, True)

            # Act
            result = await self.refresher.ensure_fresh("testuser")

        # Assert
        assert result == TokenOutcome.REFRESHED
        mock_refresh.assert_called_once_with(mock_client, mock_info, "testuser", False)

    def test_should_skip_refresh_force_refresh(self):
        """Test _should_skip_refresh returns False when force_refresh is True."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.refresher._should_skip_refresh(mock_info, True)

        # Assert
        assert result is False

    def test_should_skip_refresh_no_expiry(self):
        """Test _should_skip_refresh returns False when no expiry."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None
        self.mock_manager.validator.remaining_seconds.return_value = None

        # Act
        result = self.refresher._should_skip_refresh(mock_info, False)

        # Assert
        assert result is False

    def test_should_skip_refresh_sufficient_time(self):
        """Test _should_skip_refresh returns True when sufficient time remains."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=2)
        self.mock_manager.validator.remaining_seconds.return_value = 7200  # 2 hours

        # Act
        result = self.refresher._should_skip_refresh(mock_info, False)

        # Assert
        assert result is True

    def test_should_skip_refresh_insufficient_time(self):
        """Test _should_skip_refresh returns False when insufficient time remains."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        self.mock_manager.validator.remaining_seconds.return_value = 1800  # 30 minutes

        # Act
        result = self.refresher._should_skip_refresh(mock_info, False)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_with_lock_success(self):
        """Test _refresh_with_lock performs successful refresh."""
        # Arrange
        mock_client = AsyncMock()
        mock_info = Mock()
        mock_info.refresh_lock = AsyncMock()
        mock_info.access_token = "old_token"
        mock_info.refresh_token = "old_refresh"

        mock_result = TokenResult(
            TokenOutcome.REFRESHED,
            "new_token",
            "new_refresh",
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        mock_client.ensure_fresh.return_value = mock_result

        with patch.object(self.refresher, '_apply_successful_refresh') as mock_apply:
            with patch.object(self.mock_manager.hook_manager, 'maybe_fire_update_hook', new_callable=AsyncMock) as mock_fire_update:
                # Make the mock actually update the info
                def update_info(info, result):
                    info.access_token = result.access_token
                    info.refresh_token = result.refresh_token
                mock_apply.side_effect = update_info

                # Act
                result, changed = await self.refresher._refresh_with_lock(
                    mock_client, mock_info, "testuser", False
                )

        # Assert
        assert result == mock_result
        assert changed is True
        mock_apply.assert_called_once_with(mock_info, mock_result)
        mock_fire_update.assert_called_once_with("testuser", True)

    @pytest.mark.asyncio
    async def test_refresh_with_lock_failed_non_recoverable(self):
        """Test _refresh_with_lock handles non-recoverable failure."""
        # Arrange
        mock_client = AsyncMock()
        mock_info = Mock()
        mock_info.refresh_lock = AsyncMock()
        mock_info.state = TokenState.FRESH

        mock_result = TokenResult(TokenOutcome.FAILED, error_type=RefreshErrorType.NON_RECOVERABLE)
        mock_client.ensure_fresh.return_value = mock_result

        with patch.object(self.mock_manager.hook_manager, 'maybe_fire_invalidation_hook', new_callable=AsyncMock) as mock_fire_invalidation:
            with patch.object(self.mock_manager.hook_manager, 'maybe_fire_update_hook', new_callable=AsyncMock) as mock_fire_update:
                # Act
                result, changed = await self.refresher._refresh_with_lock(
                    mock_client, mock_info, "testuser", False
                )

        # Assert
        assert result == mock_result
        assert changed is False
        assert mock_info.state == TokenState.EXPIRED
        mock_fire_invalidation.assert_called_once_with("testuser")
        mock_fire_update.assert_called_once_with("testuser", False)

    @pytest.mark.asyncio
    async def test_refresh_with_lock_no_token_change(self):
        """Test _refresh_with_lock detects when tokens didn't change."""
        # Arrange
        mock_client = AsyncMock()
        mock_info = Mock()
        mock_info.refresh_lock = AsyncMock()
        mock_info.access_token = "same_token"
        mock_info.refresh_token = "same_refresh"

        mock_result = TokenResult(
            TokenOutcome.REFRESHED,
            "same_token",  # Same as before
            "same_refresh",  # Same as before
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        mock_client.ensure_fresh.return_value = mock_result

        with patch.object(self.refresher, '_apply_successful_refresh'):
            with patch.object(self.mock_manager.hook_manager, 'maybe_fire_update_hook', new_callable=AsyncMock) as mock_fire_update:
                # Act
                result, changed = await self.refresher._refresh_with_lock(
                    mock_client, mock_info, "testuser", False
                )

        # Assert
        assert changed is False
        mock_fire_update.assert_called_once_with("testuser", False)

    def test_apply_successful_refresh_updates_info(self):
        """Test _apply_successful_refresh updates token info correctly."""
        # Arrange
        mock_info = Mock()
        mock_result = TokenResult(
            TokenOutcome.REFRESHED,
            "new_access",
            "new_refresh",
            datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        )

        # Act
        self.refresher._apply_successful_refresh(mock_info, mock_result)

        # Assert
        assert mock_info.access_token == "new_access"
        assert mock_info.refresh_token == "new_refresh"
        assert mock_info.expiry == datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        assert mock_info.state == TokenState.FRESH

    def test_apply_successful_refresh_no_access_token(self):
        """Test _apply_successful_refresh handles None access token."""
        # Arrange
        mock_info = Mock()
        mock_info.access_token = "existing_token"
        mock_result = TokenResult(
            TokenOutcome.REFRESHED,
            None,  # No new access token
            "new_refresh",
            datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        )

        # Act
        self.refresher._apply_successful_refresh(mock_info, mock_result)

        # Assert
        assert mock_info.access_token == "existing_token"  # Should keep existing
        assert mock_info.refresh_token == "new_refresh"

    def test_apply_successful_refresh_sets_original_lifetime(self):
        """Test _apply_successful_refresh sets original_lifetime for REFRESHED outcome."""
        # Arrange
        mock_info = Mock()
        mock_now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        future_expiry = mock_now + timedelta(seconds=3600)
        mock_result = TokenResult(
            TokenOutcome.REFRESHED,
            "new_access",
            "new_refresh",
            future_expiry
        )

        with patch('src.auth_token.token_refresher.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            # Act
            self.refresher._apply_successful_refresh(mock_info, mock_result)

        # Assert
        assert mock_info.original_lifetime == 3600