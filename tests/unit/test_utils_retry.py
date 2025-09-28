"""
Unit tests for retry utilities.
"""

from unittest.mock import patch

import pytest

from src.utils.retry import RetryExhaustedError, retry_async


class TestRetryAsync:
    """Test class for retry_async functionality."""

    @pytest.mark.asyncio
    async def test_retry_async_success_first_attempt(self) -> None:
        """Test successful operation on first attempt."""
        async def operation(attempt: int) -> tuple[str, bool]:
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_async_success_after_retry(self) -> None:
        """Test successful operation after one retry."""
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return None, True  # retry
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_async_exhaust_attempts(self) -> None:
        """Test failure after exhausting max attempts."""
        async def operation(attempt: int) -> tuple[str, bool]:
            return None, True  # always retry

        with pytest.raises(RetryExhaustedError) as exc_info:
            await retry_async(operation, max_attempts=2)

        assert exc_info.value.attempts == 2
        assert "after 2 attempts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_async_exception_retry(self) -> None:
        """Test handling of exceptions that should be retried."""
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("Temporary error")
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_retry_async_exception_no_retry(self) -> None:
        """Test handling of exceptions that should not trigger retry."""
        async def operation(attempt: int) -> tuple[str, bool]:
            raise ValueError("Permanent error")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await retry_async(operation, max_attempts=1)

        assert exc_info.value.attempts == 1
        assert isinstance(exc_info.value.final_exception, Exception)

    @pytest.mark.asyncio
    async def test_retry_async_max_attempts_reached(self) -> None:
        """Test that max attempts are not exceeded."""
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            return None, True  # always retry

        with pytest.raises(RetryExhaustedError):
            await retry_async(operation, max_attempts=2)

        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_async_runtime_error(self) -> None:
        """Test handling of RuntimeError exception."""
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise RuntimeError("Runtime error")
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_async_value_error(self) -> None:
        """Test handling of ValueError exception."""
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise ValueError("Value error")
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_async_aiohttp_error(self) -> None:
        """Test handling of aiohttp.ClientError exception."""
        import aiohttp
        attempts = 0

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise aiohttp.ClientError("HTTP error")
            return "success", False

        result = await retry_async(operation, max_attempts=3)
        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_async_backoff_timing(self) -> None:
        """Test exponential backoff timing."""

        attempts = 0
        sleep_calls = []

        async def operation(attempt: int) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return None, True
            return "success", False

        with patch('asyncio.sleep', side_effect=lambda x: sleep_calls.append(x)):
            result = await retry_async(operation, max_attempts=3)
            assert result == "success"

        # Verify backoff timing (exponential: 1, 2, 4...)
        assert len(sleep_calls) == 2  # Two retries
        assert sleep_calls[0] >= 1
        assert sleep_calls[1] >= 2
