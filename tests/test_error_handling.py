"""
Tests for error_handling.py module
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.error_handling import APIError, log_error, simple_retry


class TestAPIError:
    """Test APIError exception class"""

    def test_api_error_without_status_code(self):
        """Test APIError creation without status code"""
        error = APIError("Test error message")
        assert str(error) == "Test error message"
        assert error.status_code is None

    def test_api_error_with_status_code(self):
        """Test APIError creation with status code"""
        error = APIError("Test error message", 404)
        assert str(error) == "Test error message"
        assert error.status_code == 404

    def test_api_error_inheritance(self):
        """Test that APIError inherits from Exception"""
        error = APIError("Test error")
        assert isinstance(error, Exception)


class TestSimpleRetry:
    """Test simple_retry function"""

    @pytest.mark.asyncio
    async def test_successful_first_attempt(self):
        """Test successful execution on first attempt"""
        mock_func = AsyncMock(return_value="success")

        result = await simple_retry(mock_func)

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_successful_after_retries(self):
        """Test successful execution after some retries"""
        mock_func = AsyncMock()
        mock_func.side_effect = [Exception("Error 1"), Exception("Error 2"), "success"]

        with patch('asyncio.sleep') as mock_sleep:
            result = await simple_retry(mock_func, max_retries=3, delay=1)

        assert result == "success"
        assert mock_func.call_count == 3
        # Check that sleep was called with exponential backoff
        mock_sleep.assert_any_call(1)  # First retry: 1 * 2^0 = 1
        mock_sleep.assert_any_call(2)  # Second retry: 1 * 2^1 = 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test max retries exceeded raises last exception"""
        mock_func = AsyncMock()
        mock_func.side_effect = Exception("Persistent error")

        with patch('asyncio.sleep') as mock_sleep:
            with pytest.raises(Exception, match="Persistent error"):
                await simple_retry(mock_func, max_retries=2, delay=0.5)

        assert mock_func.call_count == 3  # Initial + 2 retries
        # Check exponential backoff timing
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)

    @pytest.mark.asyncio
    async def test_custom_max_retries_and_delay(self):
        """Test custom max_retries and delay parameters"""
        mock_func = AsyncMock()
        mock_func.side_effect = [Exception("Error"), Exception("Error"), "success"]

        with patch('asyncio.sleep') as mock_sleep:
            result = await simple_retry(mock_func, max_retries=2, delay=0.1)

        assert result == "success"
        assert mock_func.call_count == 3
        # Check custom delay with exponential backoff
        mock_sleep.assert_any_call(0.1)
        mock_sleep.assert_any_call(0.2)

    @pytest.mark.asyncio
    async def test_zero_max_retries(self):
        """Test with max_retries=0 (no retries)"""
        mock_func = AsyncMock(side_effect=Exception("Error"))

        with pytest.raises(Exception, match="Error"):
            await simple_retry(mock_func, max_retries=0)

        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_user_context_in_logging(self):
        """Test that user context is included in retry logging"""
        mock_func = AsyncMock(side_effect=Exception("Test error"))

        with patch('src.error_handling.logger') as mock_logger:
            with patch('asyncio.sleep'):
                with pytest.raises(Exception):
                    await simple_retry(mock_func, max_retries=1, user="testuser")

        # Check that warning was logged with user context
        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "user=testuser" in warning_call
        assert "Test error" in warning_call

    @pytest.mark.asyncio
    async def test_no_user_context_in_logging(self):
        """Test retry logging without user context"""
        mock_func = AsyncMock(side_effect=Exception("Test error"))

        with patch('src.error_handling.logger') as mock_logger:
            with patch('asyncio.sleep'):
                with pytest.raises(Exception):
                    await simple_retry(mock_func, max_retries=1)

        # Check that warning was logged without user context
        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "user=" not in warning_call
        assert "Test error" in warning_call

    @pytest.mark.asyncio
    async def test_different_exception_types(self):
        """Test retry works with different exception types"""
        mock_func = AsyncMock()
        mock_func.side_effect = [
            ValueError("Value error"),
            RuntimeError("Runtime error"),
            "success"]

        with patch('asyncio.sleep'):
            result = await simple_retry(mock_func, max_retries=3)

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_asyncio_cancelled_error_not_retried(self):
        """Test that CancelledError is not retried (special case)"""
        mock_func = AsyncMock(side_effect=asyncio.CancelledError("Cancelled"))

        with patch('asyncio.sleep') as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await simple_retry(mock_func, max_retries=2)

        # Should not retry CancelledError
        assert mock_func.call_count == 1
        mock_sleep.assert_not_called()


class TestLogError:
    """Test log_error function"""

    def test_log_error_without_user(self):
        """Test logging error without user context"""
        test_error = Exception("Test error message")

        with patch('src.error_handling.logger') as mock_logger:
            log_error("Test message", test_error)

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert error_call == "Test message: Test error message"
        assert "user=" not in error_call

    def test_log_error_with_user(self):
        """Test logging error with user context"""
        test_error = Exception("Test error message")

        with patch('src.error_handling.logger') as mock_logger:
            log_error("Test message", test_error, user="testuser")

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert error_call == "Test message [user=testuser]: Test error message"
        assert "user=testuser" in error_call

    def test_log_error_with_empty_user(self):
        """Test logging error with empty user string (should not include user context)"""
        test_error = Exception("Test error message")

        with patch('src.error_handling.logger') as mock_logger:
            log_error("Test message", test_error, user="")

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert error_call == "Test message: Test error message"
        assert "user=" not in error_call

    def test_log_error_with_none_user(self):
        """Test logging error with None user (should be treated as no user)"""
        test_error = Exception("Test error message")

        with patch('src.error_handling.logger') as mock_logger:
            log_error("Test message", test_error, user=None)

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert error_call == "Test message: Test error message"
        assert "user=" not in error_call

    def test_log_error_with_different_error_types(self):
        """Test logging different types of errors"""
        errors_to_test = [
            ValueError("Value error"),
            RuntimeError("Runtime error"),
            ConnectionError("Connection error"),
            APIError("API error", 500)
        ]

        with patch('src.error_handling.logger') as mock_logger:
            for error in errors_to_test:
                mock_logger.reset_mock()
                log_error("Error occurred", error, user="testuser")

                mock_logger.error.assert_called_once()
                error_call = mock_logger.error.call_args[0][0]
                assert "Error occurred" in error_call
                assert "user=testuser" in error_call
                assert str(error) in error_call


class TestIntegration:
    """Integration tests for error handling components"""

    @pytest.mark.asyncio
    async def test_retry_with_api_error(self):
        """Test retry mechanism with APIError"""
        mock_func = AsyncMock()
        mock_func.side_effect = [
            APIError(
                "API Error", 500), APIError(
                "API Error", 502), "success"]

        with patch('src.error_handling.logger') as mock_logger:
            with patch('asyncio.sleep'):
                result = await simple_retry(mock_func, max_retries=2, user="testuser")

        assert result == "success"
        assert mock_func.call_count == 3

        # Check that warnings were logged with user context
        assert mock_logger.warning.call_count == 2
        for call in mock_logger.warning.call_args_list:
            warning_msg = call[0][0]
            assert "user=testuser" in warning_msg
            assert "API Error" in warning_msg

    @pytest.mark.asyncio
    async def test_retry_failure_logs_error(self):
        """Test that max retries exceeded logs final error"""
        mock_func = AsyncMock(side_effect=APIError("Persistent API Error", 500))

        with patch('src.error_handling.logger') as mock_logger:
            with patch('asyncio.sleep'):
                with pytest.raises(APIError):
                    await simple_retry(mock_func, max_retries=1, user="testuser")

        # Check that final error was logged
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "Max retries exceeded" in error_call
        assert "user=testuser" in error_call
        assert "Persistent API Error" in error_call


# Branch Coverage Tests - targeting specific uncovered branches
class TestErrorHandlingBranchCoverage:
    """Test missing branch coverage in error_handling.py"""

    @pytest.mark.asyncio
    async def test_simple_retry_asyncio_cancelled_error_not_retried(self):
        """Test that asyncio.CancelledError is not retried and exits immediately"""

        attempt_count = 0

        async def failing_func():
            nonlocal attempt_count
            attempt_count += 1
            await asyncio.sleep(0)  # Make it properly async
            raise asyncio.CancelledError("Operation cancelled")

        with pytest.raises(asyncio.CancelledError):
            await simple_retry(failing_func, max_retries=3, delay=0.01)

        # Should have only tried once, not retried
        assert attempt_count == 1

    @pytest.mark.asyncio
    async def test_simple_retry_success_on_first_attempt_early_loop_exit(self):
        """Test exact branch when function succeeds on first attempt - line 20->exit"""

        call_count = 0

        async def successful_func():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)  # Make it properly async
            return "success_value"

        # Should succeed immediately and exit the for loop early
        result = await simple_retry(successful_func, max_retries=5, delay=0.1)

        assert result == "success_value"
        assert call_count == 1  # Only called once

        # Test with different parameters to ensure it's the loop exit branch
        call_count = 0
        result2 = await simple_retry(successful_func, max_retries=0, delay=0.5)
        assert result2 == "success_value"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_simple_retry_for_loop_normal_exit(self):
        """Test for loop completion without exception - hitting the normal range exit"""
        attempts = []

        async def track_attempts():
            await asyncio.sleep(0.001)  # Make it actually async
            attempts.append(len(attempts))
            if len(attempts) <= 2:  # Fail first 2 attempts
                raise ValueError("Test error")
            return "success"  # Succeed on 3rd attempt

        # With max_retries=3, range(4) = [0,1,2,3]
        # Should succeed on attempt 2 (3rd call) and exit the for loop normally
        result = await simple_retry(track_attempts, max_retries=3)
        assert result == "success"
        assert len(attempts) == 3  # Loop exited after successful attempt

    @pytest.mark.asyncio
    async def test_simple_retry_loop_not_entered_max_retries_negative(self):
        """Cover loop exit branch where range is empty (max_retries = -1)."""
        called = False

        async def never_called():  # pragma: no cover (should not execute)
            nonlocal called
            called = True
            await asyncio.sleep(0)
            return "x"

        result = await simple_retry(never_called, max_retries=-1)
        assert result is None
        assert called is False
