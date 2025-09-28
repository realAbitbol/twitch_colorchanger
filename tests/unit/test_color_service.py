"""
Unit tests for ColorChangeService.

Tests the color change service functionality, including race condition fixes.
"""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock

from src.color.service import ColorChangeService


class TestColorChangeService:
    """Test class for ColorChangeService functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_bot = Mock()
        self.mock_bot.user_id = "test_user"
        self.mock_bot.use_random_colors = True
        self.mock_bot.last_color = None
        self.service = ColorChangeService(self.mock_bot)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_concurrent_access(self):
        """Test that _handle_hex_rejection handles concurrent access correctly."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 0
        self.mock_bot.use_random_colors = True

        # Act: Simulate concurrent calls
        tasks = [
            self.service._handle_hex_rejection(400)
            for _ in range(5)
        ]
        await asyncio.gather(*tasks)

        # Assert: Strikes should be exactly 5, not less due to race condition
        assert self.mock_bot._hex_rejection_strikes == 5

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_disables_random_colors_after_two_strikes(self):
        """Test that random colors are disabled after two strikes."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 0
        self.mock_bot.use_random_colors = True

        # Act: First strike
        await self.service._handle_hex_rejection(400)
        assert self.mock_bot._hex_rejection_strikes == 1
        assert self.mock_bot.use_random_colors is True

        # Second strike
        await self.service._handle_hex_rejection(400)
        assert self.mock_bot._hex_rejection_strikes == 2
        assert self.mock_bot.use_random_colors is False

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_with_hook(self):
        """Test that hook is called when random colors are disabled."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 1  # One strike already
        self.mock_bot.use_random_colors = True
        hook_mock = MagicMock()
        self.mock_bot.on_persistent_prime_detection = hook_mock

        # Act
        await self.service._handle_hex_rejection(400)

        # Assert
        assert self.mock_bot._hex_rejection_strikes == 2
        assert self.mock_bot.use_random_colors is False
        hook_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_async_hook(self):
        """Test that async hook is awaited when random colors are disabled."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 1
        self.mock_bot.use_random_colors = True

        async def async_hook():
            await asyncio.sleep(0.01)  # Simulate async work

        self.mock_bot.on_persistent_prime_detection = async_hook

        # Act
        await self.service._handle_hex_rejection(400)

        # Assert
        assert self.mock_bot._hex_rejection_strikes == 2
        assert self.mock_bot.use_random_colors is False

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_hook_exception_handling(self):
        """Test that hook exceptions are handled gracefully."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 1
        self.mock_bot.use_random_colors = True

        def failing_hook():
            raise ValueError("Hook failed")

        self.mock_bot.on_persistent_prime_detection = failing_hook

        # Act
        await self.service._handle_hex_rejection(400)

        # Assert
        assert self.mock_bot._hex_rejection_strikes == 2
        assert self.mock_bot.use_random_colors is False

    @pytest.mark.asyncio
    async def test_handle_hex_rejection_async_hook_exception_handling(self):
        """Test that async hook exceptions are handled gracefully."""
        # Arrange
        self.mock_bot._hex_rejection_strikes = 1
        self.mock_bot.use_random_colors = True

        async def failing_async_hook():
            raise ValueError("Async hook failed")

        self.mock_bot.on_persistent_prime_detection = failing_async_hook

        # Act
        await self.service._handle_hex_rejection(400)

        # Assert
        assert self.mock_bot._hex_rejection_strikes == 2
        assert self.mock_bot.use_random_colors is False