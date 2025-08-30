"""
Tests for Device Code Flow implementation
"""

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
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
                # Short timeout
                result = await device_flow.poll_for_tokens("test_device_code", 1)

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

    def test_handle_polling_error_authorization_pending_with_log(self, device_flow):
        """Test authorization_pending branch when poll_count triggers status log (covers wait message)."""
        # poll_count % 6 == 0 should trigger the informational log line
        with patch('src.device_flow.print_log') as mock_print:
            result = device_flow._handle_polling_error(
                {"message": "authorization_pending"}, 42, 6
            )
            assert result is None
            # Verify the waiting message was logged
            logged = "".join(call_args[0][0] for call_args in mock_print.call_args_list)
            assert "Still waiting for authorization" in logged

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
    async def test_poll_for_tokens_unexpected_response(self, device_flow):
        """Test polling path with an unexpected (non-200/400) status to cover else branch."""
        from aioresponses import aioresponses
        with aioresponses() as m:
            m.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"error": "server_error"},
                status=500
            )
            result = await device_flow.poll_for_tokens("test_device_code", 5)
            assert result is None

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

    @pytest.mark.asyncio
    async def test_poll_for_tokens_exception_during_polling(self, device_flow):
        """Test exception handling during polling (covers lines 77-78)"""
        # Simpler approach: mock the entire session to raise an exception

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                # Context manager cleanup - no action needed for test
                pass

            def post(self, *args, **kwargs):
                raise ConnectionError("Network connection error")

        with patch('aiohttp.ClientSession', return_value=MockSession()), \
                patch('src.device_flow.print_log') as mock_print_log:

            result = await device_flow.poll_for_tokens("test_device_code", 1)

            assert result is None
            # Verify the error was logged
            from src.device_flow import bcolors
            mock_print_log.assert_any_call(
                "❌ Error during polling: Network connection error",
                bcolors.FAIL
            )

    @pytest.mark.asyncio
    async def test_poll_for_tokens_real_exception_in_polling_loop(self, device_flow):
        """Test actual exception in polling loop using aioresponses (covers lines 77-78)"""

        with aioresponses() as m:
            # Mock the token endpoint to raise an exception after the first poll attempt
            def exception_callback(url, **kwargs):
                raise ConnectionError("Simulated network error")

            m.post(
                'https://id.twitch.tv/oauth2/token',
                callback=exception_callback
            )

            with patch('src.device_flow.print_log') as mock_print_log, \
                    patch('time.time', side_effect=[0, 0, 1, 2]):  # Start, first check, elapsed, timeout

                result = await device_flow.poll_for_tokens("test_device_code", 0.1)

                assert result is None
                # Verify the exception was caught and logged
                from src.device_flow import bcolors
                mock_print_log.assert_any_call(
                    "❌ Error during polling: Simulated network error",
                    bcolors.FAIL
                )

    @pytest.mark.asyncio
    async def test_handle_polling_error_with_description(self, device_flow):
        """Test error handling with error_description (covers line 124)"""
        result = device_flow._handle_polling_error(
            {"error": "invalid_grant", "error_description": "Grant has expired"},
            10, 1
        )
        assert result == {}  # Should stop polling

    @pytest.mark.asyncio
    async def test_handle_polling_error_without_description(self, device_flow):
        """Test error handling without error_description (covers line 103)"""
        result = device_flow._handle_polling_error(
            {"error": "unknown_error"},
            10, 1
        )
        assert result == {}  # Should stop polling

    @pytest.mark.asyncio
    async def test_poll_for_tokens_timeout_scenario(self, device_flow):
        """Test polling timeout scenario (covers lines 85-86)"""
        with aioresponses() as mock_responses:
            # Configure pending responses that never complete
            mock_responses.post(
                'https://id.twitch.tv/oauth2/token',
                payload={"message": "authorization_pending"},
                status=400,
                repeat=True  # Repeat indefinitely
            )

            with patch('src.device_flow.print_log') as mock_print_log, \
                    patch('asyncio.sleep', return_value=None):  # Speed up the test
                # Use a very short timeout to trigger timeout quickly
                result = await device_flow.poll_for_tokens("test_device_code", 0.1)

                assert result is None
                # Verify timeout message was logged
                from src.device_flow import bcolors
                mock_print_log.assert_any_call(
                    "❌ Device code flow timed out after 0.1s",
                    bcolors.FAIL
                )

    @pytest.mark.asyncio
    def test_lines_77_78_direct_exception_coverage(self):
        """Test that specifically covers lines 77-78 with real exception during POST"""
        async def run_real_test():
            flow = DeviceCodeFlow("test_client_id", "test_client_secret")

            async def failing_post(*args, **kwargs):
                # This will raise an exception that should be caught by lines 77-78
                raise aiohttp.ClientError("Simulated network error for coverage")

            with patch('aiohttp.ClientSession.post', new=failing_post):
                # This should trigger the exception handling on lines 77-78
                result = await flow.poll_for_tokens("device_code", expires_in=30)
                assert result is None

        asyncio.run(run_real_test())

    def test_comprehensive_exception_handling(self):
        """Comprehensive test for exception handling in polling loop"""
        async def test_execution():
            flow = DeviceCodeFlow("client_id", "client_secret")

            # Create a mock that raises an exception when post is called
            with patch('aiohttp.ClientSession') as mock_session_class:
                # Create the mock session instance
                mock_session = AsyncMock()
                mock_session_class.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock()

                # Make post raise an exception to trigger lines 77-78
                mock_session.post.side_effect = Exception("Test exception for coverage")

                # This should trigger the exception handling on lines 77-78
                result = await flow.poll_for_tokens("device_code", expires_in=30)

                # Should return None due to exception handling
                assert result is None

        asyncio.run(test_execution())

    def test_network_error_exception_handling(self):
        """Test with network-like errors to trigger exception handling"""
        async def test_execution():
            flow = DeviceCodeFlow("client_id", "client_secret")

            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock()

                # Simulate various network errors
                mock_session.post.side_effect = aiohttp.ClientError("Network error")

                result = await flow.poll_for_tokens("device_code", expires_in=30)
                assert result is None

        asyncio.run(test_execution())
