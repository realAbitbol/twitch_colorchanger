"""Tests for token_validator module."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock, Mock
import asyncio
import httpx

from src.token_validator import (
    TokenValidator,
    validate_user_tokens,
    validate_new_tokens,
)


class TestTokenValidator:
    """Test TokenValidator class."""

    def test_init(self):
        """Test TokenValidator initialization."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
            refresh_token="test_refresh",
        )
        assert validator.client_id == "test_client"
        assert validator.client_secret == "test_secret"
        assert validator.access_token == "test_token"
        assert validator.refresh_token == "test_refresh"
        assert validator._token_expiry_threshold_hours == 24

    def test_init_no_refresh_token(self):
        """Test TokenValidator initialization without refresh token."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )
        assert validator.refresh_token is None

    @pytest.mark.asyncio
    async def test_validate_token_success(self):
        """Test successful token validation."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"expires_in": 3600 * 25}  # 25 hours
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await validator.validate_token()
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_token_expires_soon_with_refresh(self):
        """Test token validation when token expires soon and has refresh token."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
            refresh_token="test_refresh",
        )

        with patch("httpx.AsyncClient") as mock_client:
            # First response: token expires soon
            validate_response = MagicMock()
            validate_response.status_code = 200
            validate_response.json.return_value = {"expires_in": 3600}  # 1 hour
            
            # Second response: refresh success
            refresh_response = MagicMock()
            refresh_response.status_code = 200
            refresh_response.json.return_value = {
                "access_token": "new_token",
                "refresh_token": "new_refresh"
            }

            client_mock = mock_client.return_value.__aenter__.return_value
            client_mock.get = AsyncMock(return_value=validate_response)
            client_mock.post = AsyncMock(return_value=refresh_response)

            result = await validator.validate_token()
            assert result is True
            assert validator.access_token == "new_token"
            assert validator.refresh_token == "new_refresh"

    @pytest.mark.asyncio
    async def test_validate_token_invalid_no_refresh(self):
        """Test token validation when token is invalid and no refresh token."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await validator.validate_token()
            assert result is False

    @pytest.mark.asyncio
    async def test_validate_token_exception(self):
        """Test token validation with exception."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Network error")
            )

            with patch("src.token_validator.print_log") as mock_log:
                result = await validator.validate_token()
                assert result is False
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
            refresh_token="test_refresh",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new_token",
                "refresh_token": "new_refresh"
            }
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await validator._refresh_token()
            assert result is True
            assert validator.access_token == "new_token"
            assert validator.refresh_token == "new_refresh"

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token(self):
        """Test token refresh without refresh token."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )

        result = await validator._refresh_token()
        assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_failure(self):
        """Test token refresh failure."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
            refresh_token="test_refresh",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with patch("src.token_validator.print_log") as mock_log:
                result = await validator._refresh_token()
                assert result is False
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_token_exception(self):
        """Test token refresh with exception."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
            refresh_token="test_refresh",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Network error")
            )

            with patch("src.token_validator.print_log") as mock_log:
                result = await validator._refresh_token()
                assert result is False
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_check_and_refresh_token_force_no_refresh(self):
        """Test forced check without refresh token."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="test_token",
        )

        with patch.object(validator, "validate_token", return_value=True) as mock_validate:
            result = await validator.check_and_refresh_token(force=True)
            assert result is True
            mock_validate.assert_called_once()

    @pytest.mark.asyncio
    def test_check_and_refresh_token_force_with_refresh(self):
        """Test check_and_refresh_token with force=True and refresh token."""
        validator = TokenValidator(
            access_token="test_token",
            refresh_token="test_refresh",
            client_id="test_client",
            client_secret="test_secret"
        )

        with patch.object(validator, '_refresh_token') as mock_refresh:
            mock_refresh.return_value = True
            result = asyncio.run(validator.check_and_refresh_token(force=True))
            assert result is True
            mock_refresh.assert_called_once()

    def test_validate_token_invalid_no_refresh_token(self):
        """Test validate_token when token is invalid and no refresh token."""
        validator = TokenValidator(
            access_token="test_token",
            refresh_token=None,  # No refresh token
            client_id="test_client",
            client_secret="test_secret"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"status": 401, "message": "invalid access token"}
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = asyncio.run(validator.validate_token())
            assert result is False

    def test_validate_token_expires_soon_no_refresh_token(self):
        """Test validate_token when token expires soon but no refresh token."""
        validator = TokenValidator(
            access_token="test_token",
            refresh_token=None,  # No refresh token
            client_id="test_client",
            client_secret="test_secret"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "expires_in": 1800,  # 30 minutes - less than 2 hour threshold
                "user_id": "123456"
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = asyncio.run(validator.validate_token())
            # When token expires soon but no refresh token, it falls through to return True
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_token_invalid_with_refresh_token(self):
        """Test validate_token when token is invalid but a refresh token exists (covers branch)."""
        validator = TokenValidator(
            client_id="test_client",
            client_secret="test_secret",
            access_token="expired_token",
            refresh_token="refresh_token_value",
        )

        # Patch httpx client to return 401 for validation, and refresh flow to return False
        with patch("httpx.AsyncClient") as mock_client, patch.object(
            validator, "_refresh_token", new=AsyncMock(return_value=False)
        ) as mock_refresh:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"status": 401, "message": "invalid access token"}
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await validator.validate_token()
            # Should attempt refresh and propagate its False result
            assert result is False
            mock_refresh.assert_awaited_once()

    def test_check_and_refresh_token_no_force_no_refresh_token(self):
        """Test check_and_refresh_token with force=False and no refresh token."""
        validator = TokenValidator(
            access_token="test_token",
            refresh_token=None,  # No refresh token
            client_id="test_client",
            client_secret="test_secret"
        )

        with patch.object(validator, 'validate_token') as mock_validate:
            mock_validate.return_value = True
            result = asyncio.run(validator.check_and_refresh_token(force=False))
            assert result is True
            mock_validate.assert_called_once()


class TestValidateUserTokens:
    """Test validate_user_tokens function."""

    @pytest.mark.asyncio
    async def test_validate_user_tokens_no_access_token(self):
        """Test validation with no access token."""
        user = {"username": "testuser"}
        
        with patch("src.token_validator.print_log") as mock_log:
            result = await validate_user_tokens(user)
            assert result["valid"] is False
            assert result["updated"] is False
            mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_user_tokens_missing_credentials(self):
        """Test validation with missing client credentials."""
        user = {
            "username": "testuser",
            "access_token": "token",
        }
        
        with patch("src.token_validator.print_log") as mock_log:
            result = await validate_user_tokens(user)
            assert result["valid"] is False
            assert result["updated"] is False
            mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_user_tokens_success_no_update(self):
        """Test successful validation without token update."""
        user = {
            "username": "testuser",
            "access_token": "token",
            "refresh_token": "refresh",
            "client_id": "client",
            "client_secret": "secret",
        }

        with patch("src.token_validator.TokenValidator") as mock_validator_class:
            mock_validator = MagicMock()
            mock_validator.check_and_refresh_token = AsyncMock(return_value=True)
            mock_validator.access_token = "token"  # Same token
            mock_validator.refresh_token = "refresh"  # Same refresh token
            mock_validator_class.return_value = mock_validator

            result = await validate_user_tokens(user)
            assert result["valid"] is True
            assert result["updated"] is False

    @pytest.mark.asyncio
    async def test_validate_user_tokens_success_with_update(self):
        """Test successful validation with token update."""
        user = {
            "username": "testuser",
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "client_id": "client",
            "client_secret": "secret",
        }

        with patch("src.token_validator.TokenValidator") as mock_validator_class:
            mock_validator = MagicMock()
            mock_validator.check_and_refresh_token = AsyncMock(return_value=True)
            mock_validator.access_token = "new_token"  # Updated token
            mock_validator.refresh_token = "new_refresh"  # Updated refresh token
            mock_validator_class.return_value = mock_validator

            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_user_tokens(user)
                assert result["valid"] is True
                assert result["updated"] is True
                assert user["access_token"] == "new_token"
                assert user["refresh_token"] == "new_refresh"
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_user_tokens_validation_failed(self):
        """Test validation failure."""
        user = {
            "username": "testuser",
            "access_token": "token",
            "refresh_token": "refresh",
            "client_id": "client",
            "client_secret": "secret",
        }

        with patch("src.token_validator.TokenValidator") as mock_validator_class:
            mock_validator = MagicMock()
            mock_validator.check_and_refresh_token = AsyncMock(return_value=False)
            mock_validator_class.return_value = mock_validator

            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_user_tokens(user)
                assert result["valid"] is False
                assert result["updated"] is False
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_user_tokens_exception(self):
        """Test validation with exception."""
        user = {
            "username": "testuser",
            "access_token": "token",
            "refresh_token": "refresh",
            "client_id": "client",
            "client_secret": "secret",
        }

        with patch("src.token_validator.TokenValidator", side_effect=Exception("Error")):
            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_user_tokens(user)
                assert result["valid"] is False
                assert result["updated"] is False
                mock_log.assert_called()


class TestValidateNewTokens:
    """Test validate_new_tokens function."""

    @pytest.mark.asyncio
    async def test_validate_new_tokens_missing_key(self):
        """Test validation with missing required key."""
        user = {
            "username": "testuser",
            "client_id": "client",
            # Missing client_secret, access_token, refresh_token
        }

        with patch("src.token_validator.print_log") as mock_log:
            result = await validate_new_tokens(user)
            assert result["valid"] is False
            mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_new_tokens_success(self):
        """Test successful new token validation."""
        user = {
            "username": "testuser",
            "client_id": "client",
            "client_secret": "secret",
            "access_token": "token",
            "refresh_token": "refresh",
        }

        with patch("src.token_validator.TokenValidator") as mock_validator_class:
            mock_validator = MagicMock()
            mock_validator.validate_token = AsyncMock(return_value=True)
            mock_validator.access_token = "token"
            mock_validator.refresh_token = "refresh"
            mock_validator_class.return_value = mock_validator

            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_new_tokens(user)
                assert result["valid"] is True
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_new_tokens_failure(self):
        """Test new token validation failure."""
        user = {
            "username": "testuser",
            "client_id": "client",
            "client_secret": "secret",
            "access_token": "token",
            "refresh_token": "refresh",
        }

        with patch("src.token_validator.TokenValidator") as mock_validator_class:
            mock_validator = MagicMock()
            mock_validator.validate_token = AsyncMock(return_value=False)
            mock_validator_class.return_value = mock_validator

            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_new_tokens(user)
                assert result["valid"] is False
                mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_validate_new_tokens_exception(self):
        """Test new token validation with exception."""
        user = {
            "username": "testuser",
            "client_id": "client",
            "client_secret": "secret",
            "access_token": "token",
            "refresh_token": "refresh",
        }

        with patch("src.token_validator.TokenValidator", side_effect=Exception("Error")):
            with patch("src.token_validator.print_log") as mock_log:
                result = await validate_new_tokens(user)
                assert result["valid"] is False
                mock_log.assert_called()
