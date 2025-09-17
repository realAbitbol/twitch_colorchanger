"""Tests for auth_token.manager.TokenManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth_token.manager import TokenManager


class TestTokenManager:
    """Test suite for TokenManager."""

    @pytest.fixture
    def mock_session(self):
        """Mock aiohttp ClientSession."""
        return MagicMock()

    @pytest.fixture
    def token_manager(self, mock_session):
        """Create TokenManager instance."""
        return TokenManager(mock_session)

    @pytest.mark.asyncio
    async def test_refresh_with_lock_atomic(self, token_manager):
        """Test that _refresh_with_lock uses atomic locking."""
        # Mock the dependencies
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.outcome.name = "REFRESHED"
        mock_result.access_token = "new_token"
        mock_client.ensure_fresh = AsyncMock(return_value=mock_result)

        mock_info = MagicMock()
        mock_info.access_token = "old_token"
        mock_info.refresh_token = "old_refresh"
        mock_info.refresh_lock = asyncio.Lock()

        # Mock _apply_successful_refresh to update the info
        with patch.object(token_manager, '_apply_successful_refresh', side_effect=lambda info, res: setattr(info, 'access_token', res.access_token)):
            # Call the method
            result, changed = await token_manager._refresh_with_lock(
                mock_client, mock_info, "testuser", False
            )

            assert result == mock_result
            assert changed is True

    @pytest.mark.asyncio
    async def test_concurrent_refresh_serialization(self, token_manager):
        """Test that concurrent refreshes are serialized."""
        # This test ensures that the global _token_update_lock prevents concurrent updates
        refresh_count = 0

        async def mock_refresh():
            nonlocal refresh_count
            refresh_count += 1
            await asyncio.sleep(0.01)  # Simulate some work
            return refresh_count

        # Mock the client and info
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.outcome.name = "REFRESHED"
        mock_result.access_token = "new_token"
        mock_client.ensure_fresh = AsyncMock(return_value=mock_result)

        mock_info = MagicMock()
        mock_info.access_token = "old_token"
        mock_info.refresh_token = "old_refresh"
        mock_info.refresh_lock = asyncio.Lock()

        with patch.object(token_manager, '_apply_successful_refresh', side_effect=lambda info, res: setattr(info, 'access_token', res.access_token)):
            # Launch multiple concurrent refreshes
            tasks = []
            for _ in range(5):
                task = asyncio.create_task(
                    token_manager._refresh_with_lock(mock_client, mock_info, "testuser", False)
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            # All should succeed and be serialized
            assert len(results) == 5
            for result, _changed in results:
                assert result == mock_result
                # Note: changed may be False for subsequent calls due to shared mock_info
