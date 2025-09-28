"""
Unit tests for TokenValidator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
from freezegun import freeze_time

from src.auth_token.token_validator import TokenValidator
from src.auth_token.client import TokenOutcome


class TestTokenValidator:
    """Test class for TokenValidator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_manager = Mock()
        self.mock_manager._tokens_lock = AsyncMock()
        self.validator = TokenValidator(self.mock_manager)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_validate_no_token_info(self):
        """Test validate returns FAILED when no token info exists."""
        # Arrange
        self.mock_manager.tokens = {}

        # Act
        result = await self.validator.validate("nonexistent_user")

        # Assert
        assert result == TokenOutcome.FAILED

    @pytest.mark.asyncio
    async def test_validate_recent_validation_skipped(self):
        """Test validate returns VALID when validation was recent."""
        # Arrange
        mock_info = Mock()
        mock_info.last_validation = 1000.0  # Recent
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        self.mock_manager.tokens = {"testuser": mock_info}

        with patch('time.time', return_value=1001.0):  # Just over 1 second ago
            # Act
            result = await self.validator.validate("testuser")

        # Assert
        assert result == TokenOutcome.VALID

    @pytest.mark.asyncio
    async def test_validate_no_expiry_fails(self):
        """Test validate returns FAILED when token has no expiry."""
        # Arrange
        mock_info = Mock()
        mock_info.last_validation = 0
        mock_info.expiry = None
        self.mock_manager.tokens = {"testuser": mock_info}

        # Act
        result = await self.validator.validate("testuser")

        # Assert
        assert result == TokenOutcome.FAILED

    @pytest.mark.asyncio
    async def test_validate_success(self):
        """Test validate succeeds and updates token info."""
        # Arrange
        mock_info = Mock()
        mock_info.last_validation = 0
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_info.client_id = "client123"
        mock_info.client_secret = "secret123"
        mock_info.access_token = "token123"
        self.mock_manager.tokens = {"testuser": mock_info}

        mock_client = AsyncMock()
        mock_client._validate_remote.return_value = (True, datetime.now(timezone.utc) + timedelta(hours=2))
        self.mock_manager.client_cache.get_client = AsyncMock(return_value=mock_client)

        with patch('time.time', return_value=1000.0):
            # Act
            result = await self.validator.validate("testuser")

        # Assert
        assert result == TokenOutcome.VALID
        assert mock_info.last_validation == 1000.0
        self.mock_manager.client_cache.get_client.assert_called_once_with("client123", "secret123")
        mock_client._validate_remote.assert_called_once_with("testuser", "token123")

    @pytest.mark.asyncio
    async def test_validate_remote_failure(self):
        """Test validate returns FAILED when remote validation fails."""
        # Arrange
        mock_info = Mock()
        mock_info.last_validation = 0
        mock_info.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_info.client_id = "client123"
        mock_info.client_secret = "secret123"
        mock_info.access_token = "token123"
        self.mock_manager.tokens = {"testuser": mock_info}

        mock_client = AsyncMock()
        mock_client._validate_remote.return_value = (False, None)
        self.mock_manager.client_cache.get_client = AsyncMock(return_value=mock_client)

        with patch('time.time', return_value=1000.0):
            # Act
            result = await self.validator.validate("testuser")

        # Assert
        assert result == TokenOutcome.FAILED
        assert mock_info.last_validation == 1000.0

    def test_remaining_seconds_with_expiry(self):
        """Test remaining_seconds calculates correctly with expiry."""
        # Arrange
        mock_info = Mock()
        future_time = datetime.now(timezone.utc) + timedelta(seconds=3600)
        mock_info.expiry = future_time

        # Act
        result = self.validator.remaining_seconds(mock_info)

        # Assert
        assert result is not None
        assert 3599 <= result <= 3601  # Allow small timing variance

    def test_remaining_seconds_no_expiry(self):
        """Test remaining_seconds returns None when no expiry."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None

        # Act
        result = self.validator.remaining_seconds(mock_info)

        # Assert
        assert result is None

    def test_assess_token_health_unknown_expiry(self):
        """Test assess_token_health returns degraded for unknown expiry."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.validator.assess_token_health(mock_info, None, 0)

        # Assert
        assert result == "degraded"

    def test_assess_token_health_expired(self):
        """Test assess_token_health returns critical for expired token."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.validator.assess_token_health(mock_info, -100, 0)

        # Assert
        assert result == "critical"

    def test_assess_token_health_critical_with_drift(self):
        """Test assess_token_health returns critical for token near expiry with high drift."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.validator.assess_token_health(mock_info, 250, 70)  # 250s left, 70s drift

        # Assert
        assert result == "critical"

    def test_assess_token_health_degraded(self):
        """Test assess_token_health returns degraded for token approaching expiry with drift."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.validator.assess_token_health(mock_info, 1800, 40)  # 30 min left, 40s drift

        # Assert
        assert result == "degraded"

    def test_assess_token_health_healthy(self):
        """Test assess_token_health returns healthy for fresh token."""
        # Arrange
        mock_info = Mock()

        # Act
        result = self.validator.assess_token_health(mock_info, 7200, 10)  # 2 hours left, low drift

        # Assert
        assert result == "healthy"

    @freeze_time("2023-01-01 12:00:00")
    def test_remaining_seconds_calculation(self):
        """Test remaining_seconds calculation with frozen time."""
        # Arrange
        mock_info = Mock()
        # Set expiry to 1 hour from frozen time
        mock_info.expiry = datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        # Act
        result = self.validator.remaining_seconds(mock_info)

        # Assert
        assert result == 3600.0