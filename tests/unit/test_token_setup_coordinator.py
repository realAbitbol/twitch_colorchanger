"""
Unit tests for TokenSetupCoordinator.
"""

import pytest
import aiohttp
from unittest.mock import Mock, AsyncMock, patch

from src.config.token_setup_coordinator import TokenSetupCoordinator


class TestTokenSetupCoordinator:
    """Test class for TokenSetupCoordinator functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.coordinator = TokenSetupCoordinator()

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    def test_init_with_saver(self):
        """Test TokenSetupCoordinator initialization with custom saver."""
        mock_saver = Mock()
        coordinator = TokenSetupCoordinator(saver=mock_saver)
        assert coordinator.saver == mock_saver

    def test_init_without_saver(self):
        """Test TokenSetupCoordinator initialization without saver creates default."""
        coordinator = TokenSetupCoordinator()
        assert coordinator.saver is not None

    @pytest.mark.asyncio
    async def test_setup_missing_tokens_processes_users(self):
        """Test setup_missing_tokens processes all users."""
        mock_users = [Mock(), Mock()]
        mock_users[0].access_token = None
        mock_users[1].access_token = "existing_token"

        with patch('aiohttp.ClientSession') as mock_session:
            with patch.object(self.coordinator, '_process_single_user_tokens_dataclass') as mock_process:
                mock_process.side_effect = [(True, mock_users[0]), (False, mock_users[1])]

                with patch.object(self.coordinator, '_save_updated_config_dataclass') as mock_save:
                    result = await self.coordinator.setup_missing_tokens(mock_users, "test.conf")

        assert result == mock_users
        assert mock_process.call_count == 2
        mock_save.assert_called_once_with(mock_users, "test.conf")

    @pytest.mark.asyncio
    async def test_setup_missing_tokens_no_updates(self):
        """Test setup_missing_tokens when no updates are needed."""
        mock_users = [Mock()]
        mock_users[0].access_token = "existing_token"

        with patch('aiohttp.ClientSession'):
            with patch.object(self.coordinator, '_process_single_user_tokens_dataclass') as mock_process:
                mock_process.return_value = (False, mock_users[0])

                result = await self.coordinator.setup_missing_tokens(mock_users, "test.conf")

        assert result == mock_users
        # _save_updated_config_dataclass should not be called when no updates

    def test_missing_scopes_calculates_correctly(self):
        """Test _missing_scopes calculates missing scopes correctly."""
        required = {"scope1", "scope2", "scope3"}
        current = {"scope1", "scope4"}

        result = self.coordinator._missing_scopes(required, current)

        assert set(result) == {"scope2", "scope3"}
        assert result == sorted(result)  # Should be sorted

    @pytest.mark.asyncio
    async def test_validate_or_invalidate_scopes_valid_tokens(self):
        """Test _validate_or_invalidate_scopes returns True for valid tokens."""
        mock_user = Mock()
        access = "token123"
        refresh = "refresh123"

        mock_api = AsyncMock()
        mock_api.validate_token.return_value = {"scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]}

        required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

        result = await self.coordinator._validate_or_invalidate_scopes(
            mock_user, access, refresh, mock_api, required_scopes
        )

        assert result is True
        mock_api.validate_token.assert_called_once_with(access)

    @pytest.mark.asyncio
    async def test_validate_or_invalidate_scopes_missing_scopes(self):
        """Test _validate_or_invalidate_scopes invalidates tokens with missing scopes."""
        mock_user = Mock()
        access = "token123"
        refresh = "refresh123"

        mock_api = AsyncMock()
        mock_api.validate_token.return_value = {"scopes": ["chat:read"]}

        required_scopes = {"chat:read", "user:read:chat", "user:manage:chat_color"}

        with patch.object(self.coordinator, '_invalidate_for_missing_scopes') as mock_invalidate:
            result = await self.coordinator._validate_or_invalidate_scopes(
                mock_user, access, refresh, mock_api, required_scopes
            )

        assert result is False
        mock_invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_or_invalidate_scopes_no_tokens(self):
        """Test _validate_or_invalidate_scopes returns False when no tokens."""
        mock_user = Mock()
        access = None
        refresh = None

        mock_api = AsyncMock()

        result = await self.coordinator._validate_or_invalidate_scopes(
            mock_user, access, refresh, mock_api, {"scope1"}
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_or_invalidate_scopes_validation_failure(self):
        """Test _validate_or_invalidate_scopes handles validation failures gracefully."""
        mock_user = Mock()
        access = "token123"
        refresh = "refresh123"

        mock_api = AsyncMock()
        mock_api.validate_token.side_effect = aiohttp.ClientError("Validation failed")

        required_scopes = {"chat:read"}

        result = await self.coordinator._validate_or_invalidate_scopes(
            mock_user, access, refresh, mock_api, required_scopes
        )

        assert result is True  # Should retain tokens on validation failure

    def test_invalidate_for_missing_scopes_dict_user(self):
        """Test _invalidate_for_missing_scopes handles dict users."""
        user = {
            "username": "testuser",
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "token_expiry": "2023-01-01"
        }
        required_scopes = {"scope1", "scope2"}
        current_set = {"scope1"}

        with patch('src.config.token_setup_coordinator.logging') as mock_logging:
            self.coordinator._invalidate_for_missing_scopes(user, required_scopes, current_set)

        assert user.get("access_token") is None
        assert user.get("refresh_token") is None
        assert user.get("token_expiry") is None
        mock_logging.warning.assert_called_once()

    def test_invalidate_for_missing_scopes_dataclass_user(self):
        """Test _invalidate_for_missing_scopes handles UserConfig users."""
        user = Mock()
        user.username = "testuser"
        user.access_token = "old_token"
        user.refresh_token = "old_refresh"

        required_scopes = {"scope1", "scope2"}
        current_set = {"scope1"}

        with patch('src.config.token_setup_coordinator.logging') as mock_logging:
            self.coordinator._invalidate_for_missing_scopes(user, required_scopes, current_set)

        assert user.access_token is None
        assert user.refresh_token is None
        mock_logging.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_single_user_tokens_dataclass_provisions_new_tokens(self):
        """Test _process_single_user_tokens_dataclass provisions new tokens when needed."""
        mock_user = Mock()
        mock_user.username = "testuser"
        mock_user.client_id = "client123"
        mock_user.client_secret = "secret123"
        mock_user.access_token = None
        mock_user.refresh_token = None

        mock_api = AsyncMock()
        mock_provisioner = AsyncMock()
        mock_provisioner.provision.return_value = ("new_access", "new_refresh", None)

        required_scopes = {"chat:read"}

        with patch.object(self.coordinator, '_validate_or_invalidate_scopes', return_value=False):
            result_changed, result_user = await self.coordinator._process_single_user_tokens_dataclass(
                mock_user, mock_api, mock_provisioner, required_scopes
            )

        assert result_changed is True
        assert result_user == mock_user
        assert mock_user.access_token == "new_access"
        assert mock_user.refresh_token == "new_refresh"
        mock_provisioner.provision.assert_called_once_with(
            "testuser", "client123", "secret123", None, None, None
        )

    @pytest.mark.asyncio
    async def test_process_single_user_tokens_dataclass_keeps_valid_tokens(self):
        """Test _process_single_user_tokens_dataclass keeps valid existing tokens."""
        mock_user = Mock()
        mock_user.access_token = "existing_token"
        mock_user.refresh_token = "existing_refresh"

        mock_api = AsyncMock()
        mock_provisioner = AsyncMock()

        required_scopes = {"chat:read"}

        with patch.object(self.coordinator, '_validate_or_invalidate_scopes', return_value=True):
            result_changed, result_user = await self.coordinator._process_single_user_tokens_dataclass(
                mock_user, mock_api, mock_provisioner, required_scopes
            )

        assert result_changed is False
        assert result_user == mock_user
        # Provisioner should not be called
        mock_provisioner.provision.assert_not_called()

    def test_save_updated_config_dataclass_calls_saver(self):
        """Test _save_updated_config_dataclass calls saver correctly."""
        mock_users = [Mock(), Mock()]

        with patch.object(self.coordinator.saver, 'save_users_to_config') as mock_save:
            with patch('src.config.token_setup_coordinator.logging') as mock_logging:
                self.coordinator._save_updated_config_dataclass(mock_users, "test.conf")

        mock_save.assert_called_once()
        mock_logging.info.assert_called_once_with("💾 Tokens update saved")

    def test_save_updated_config_dataclass_handles_exceptions(self):
        """Test _save_updated_config_dataclass handles save exceptions."""
        mock_users = [Mock()]

        with patch.object(self.coordinator.saver, 'save_users_to_config', side_effect=OSError("Save failed")):
            with patch('src.config.token_setup_coordinator.logging') as mock_logging:
                self.coordinator._save_updated_config_dataclass(mock_users, "test.conf")

        mock_logging.error.assert_called_once()