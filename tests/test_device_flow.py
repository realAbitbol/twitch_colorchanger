"""
Tests for Device Code Flow implementation
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from aioresponses import aioresponses
from src.device_flow import DeviceCodeFlow


class TestDeviceCodeFlow:
    """Test Device Code Flow functionality"""

    @pytest.fixture
    def device_flow(self):
        """Create a DeviceCodeFlow instance for testing"""
        return DeviceCodeFlow(
            client_id="test_client_id",
            client_secret="test_client_secret"
        )

    def test_init(self, device_flow):
        """Test DeviceCodeFlow initialization"""
        assert device_flow.client_id == "test_client_id"
        assert device_flow.client_secret == "test_client_secret"
        assert device_flow.device_code_url == "https://id.twitch.tv/oauth2/device"
        assert device_flow.token_url == "https://id.twitch.tv/oauth2/token"
        assert device_flow.poll_interval == 5

    @pytest.mark.asyncio
    async def test_request_device_code_success(self, device_flow):
        """Test successful device code request"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/device',
                payload={
                    "device_code": "test_device_code",
                    "user_code": "TEST123",
                    "verification_uri": "https://www.twitch.tv/activate",
                    "expires_in": 1800,
                    "interval": 5
                },
                status=200
            )
            
            result = await device_flow.request_device_code()

            assert result is not None
            assert result["device_code"] == "test_device_code"
            assert result["user_code"] == "TEST123"
            assert result["verification_uri"] == "https://www.twitch.tv/activate"
            assert result["expires_in"] == 1800

    @pytest.mark.asyncio
    async def test_request_device_code_failure(self, device_flow):
        """Test device code request failure"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/device',
                payload={"error": "invalid_client"},
                status=400
            )
            
            result = await device_flow.request_device_code()

            assert result is None

    @pytest.mark.asyncio
    async def test_request_device_code_exception(self, device_flow):
        """Test device code request with network exception"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/device',
                exception=Exception("Network error")
            )
            
            result = await device_flow.request_device_code()

            assert result is None

    @pytest.mark.asyncio
    async def test_poll_for_tokens_success(self, device_flow):
        """Test successful token polling"""
        with aioresponses() as m:
            # Mock successful token response
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={
                    "access_token": "test_access_token",
                    "refresh_token": "test_refresh_token",
                    "expires_in": 3600,
                    "token_type": "bearer"
                },
                status=200
            )
            
            with patch('asyncio.sleep'):  # Mock sleep to speed up test
                result = await device_flow.poll_for_tokens("test_device_code", 30)

                assert result is not None
                assert result["access_token"] == "test_access_token"
                assert result["refresh_token"] == "test_refresh_token"

    @pytest.mark.asyncio
    async def test_poll_for_tokens_timeout(self, device_flow):
        """Test token polling timeout"""
        # Mock pending authorization response
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.json.return_value = {"message": "authorization_pending"}

        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.post.return_value.__aexit__.return_value = None

        with patch('aiohttp.ClientSession', return_value=mock_session):
            with patch('asyncio.sleep'):  # Mock sleep to speed up test
                result = await device_flow.poll_for_tokens("test_device_code", 1)  # Short timeout

                assert result is None

    @pytest.mark.asyncio
    async def test_poll_for_tokens_access_denied(self, device_flow):
        """Test token polling with access denied"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"message": "access_denied"},
                status=400
            )
            
            result = await device_flow.poll_for_tokens("test_device_code", 30)

            assert result == {}

    @pytest.mark.asyncio
    async def test_poll_for_tokens_expired_token(self, device_flow):
        """Test token polling with expired device code"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"message": "expired_token"},
                status=400
            )
            
            result = await device_flow.poll_for_tokens("test_device_code", 30)

            assert result == {}

    @pytest.mark.asyncio
    async def test_poll_for_tokens_slow_down(self, device_flow):
        """Test token polling with slow_down response"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"message": "slow_down"},
                status=400
            )
            
            result = await device_flow.poll_for_tokens("test_device_code", 30)

            # Should continue polling (return None) and increase poll interval
            assert result is None
            assert device_flow.poll_interval > 5  # Should have increased from default 5

    def test_handle_polling_error_authorization_pending(self, device_flow):
        """Test handling authorization_pending error"""
        result = device_flow._handle_polling_error(
            {"message": "authorization_pending"}, 10, 1
        )
        assert result is None  # Should continue polling

    def test_handle_polling_error_slow_down(self, device_flow):
        """Test handling slow_down error"""
        initial_interval = device_flow.poll_interval
        result = device_flow._handle_polling_error(
            {"message": "slow_down"}, 10, 1
        )
        assert result is None  # Should continue polling
        assert device_flow.poll_interval > initial_interval  # Should increase interval

    def test_handle_polling_error_expired_token(self, device_flow):
        """Test handling expired_token error"""
        result = device_flow._handle_polling_error(
            {"message": "expired_token"}, 10, 1
        )
        assert result == {}  # Should stop polling

    def test_handle_polling_error_access_denied(self, device_flow):
        """Test handling access_denied error"""
        result = device_flow._handle_polling_error(
            {"message": "access_denied"}, 10, 1
        )
        assert result == {}  # Should stop polling

    def test_handle_polling_error_unknown_error(self, device_flow):
        """Test handling unknown error"""
        result = device_flow._handle_polling_error(
            {"message": "unknown_error", "error_description": "Something went wrong"}, 10, 1
        )
        assert result == {}  # Should stop polling

    @pytest.mark.asyncio
    async def test_get_user_tokens_success(self, device_flow):
        """Test successful complete token flow"""
        with aioresponses() as m:
            # Mock device code response
            m.post(
                'https://id.twitch.tv/oauth2/device',
                payload={
                    "device_code": "test_device_code",
                    "user_code": "TEST123",
                    "verification_uri": "https://www.twitch.tv/activate",
                    "expires_in": 1800
                },
                status=200
            )
            
            # Mock token response
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={
                    "access_token": "test_access_token",
                    "refresh_token": "test_refresh_token",
                    "expires_in": 3600
                },
                status=200
            )
            
            with patch('asyncio.sleep'):  # Speed up polling
                result = await device_flow.get_user_tokens("testuser")

                assert result is not None
                assert result[0] == "test_access_token"  # access_token
                assert result[1] == "test_refresh_token"  # refresh_token

    @pytest.mark.asyncio
    async def test_get_user_tokens_device_code_failure(self, device_flow):
        """Test token flow failure at device code step"""
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/device',
                payload={"error": "invalid_client"},
                status=400
            )
            
            result = await device_flow.get_user_tokens("testuser")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_user_tokens_polling_failure(self, device_flow):
        """Test token flow failure at polling step"""
        with aioresponses() as m:
            # Mock successful device code response
            m.post(
                'https://id.twitch.tv/oauth2/device',
                payload={
                    "device_code": "test_device_code",
                    "user_code": "TEST123",
                    "verification_uri": "https://www.twitch.tv/activate",
                    "expires_in": 1  # Very short timeout
                },
                status=200
            )
            
            # Mock failed token response (always pending)
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"message": "authorization_pending"},
                status=400
            )
            
            with patch('asyncio.sleep'):  # Speed up polling
                result = await device_flow.get_user_tokens("testuser")

                assert result is None
