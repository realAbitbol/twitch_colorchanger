"""Unit and integration tests for src/errors/handling.py."""


import functools
from unittest.mock import patch

import aiohttp
import pytest

from src.errors.handling import handle_api_error, handle_retryable_error
from src.errors.internal import (
    InternalError,
    NetworkError,
    OAuthError,
    ParsingError,
    RateLimitError,
)
from src.utils.retry import retry_async


def fast_backoff(attempt):
    return 0


fast_retry_async = functools.partial(retry_async, backoff_func=fast_backoff)


async def no_sleep_retry_async(operation, max_attempts=6, backoff_func=None):
    """Retry async operation without sleeping."""
    for attempt in range(max_attempts):
        try:
            result, should_retry = await operation(attempt)
            if not should_retry:
                return result
        except (RuntimeError, ValueError, OSError, aiohttp.ClientError):
            should_retry = attempt < max_attempts - 1
            if not should_retry:
                raise
        # No sleep
    return None


@pytest.mark.asyncio
async def test_handle_api_error_success():
    """Test handle_api_error with successful operation."""
    async def operation():
        return "success"

    result = await handle_api_error(operation, "test context")
    assert result == "success"


@pytest.mark.asyncio
async def test_handle_api_error_client_error():
    """Test handle_api_error with aiohttp.ClientError."""
    async def operation():
        raise aiohttp.ClientError("Test client error")

    with pytest.raises(InternalError) as exc_info:
        await handle_api_error(operation, "test context")
    assert "Unexpected error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_api_error_timeout():
    """Test handle_api_error with TimeoutError."""
    async def operation():
        raise TimeoutError("Test timeout")

    with pytest.raises(NetworkError) as exc_info:
        await handle_api_error(operation, "test context")
    assert "Network error" in str(exc_info.value)


class MockResponseError(aiohttp.ClientError):
    def __init__(self, status):
        super().__init__("Mock error")
        self.status = status


@pytest.mark.asyncio
async def test_handle_api_error_401():
    """Test handle_api_error with 401 status."""
    async def operation():
        raise MockResponseError(401)

    with pytest.raises(OAuthError) as exc_info:
        await handle_api_error(operation, "test context")
    assert "Authentication error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_api_error_429():
    """Test handle_api_error with 429 status."""
    async def operation():
        raise MockResponseError(429)

    with pytest.raises(RateLimitError) as exc_info:
        await handle_api_error(operation, "test context")
    assert "Rate limit exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_api_error_400():
    """Test handle_api_error with 400 status."""
    async def operation():
        raise MockResponseError(400)

    with pytest.raises(ParsingError) as exc_info:
        await handle_api_error(operation, "test context")
    assert "Client error" in str(exc_info.value)


@patch('src.utils.retry.retry_async', no_sleep_retry_async)
@pytest.mark.asyncio
async def test_handle_retryable_error_success_first():
    """Test handle_retryable_error success on first attempt."""
    async def operation(attempt):
        return "success", False

    result = await handle_retryable_error(operation, "test context", max_attempts=3)
    assert result == "success"


@patch('src.utils.retry.retry_async', no_sleep_retry_async)
@pytest.mark.asyncio
async def test_handle_retryable_error_retry_success():
    """Test handle_retryable_error success after retry."""
    call_count = 0

    async def operation(attempt):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("Test error")
        return "success", False

    result = await handle_retryable_error(operation, "test context", max_attempts=3)
    assert result == "success"
    assert call_count == 2

@patch('src.utils.retry.retry_async', fast_retry_async)

@pytest.mark.asyncio
async def test_handle_retryable_error_max_attempts():
    """Test handle_retryable_error exhausts max attempts."""
    async def operation(attempt):
        raise ConnectionError("Test error")

    with pytest.raises(InternalError) as exc_info:
        await handle_retryable_error(operation, "test context", max_attempts=2)
    assert "Non-retryable error" in str(exc_info.value)


@patch('src.utils.retry.retry_async', no_sleep_retry_async)
@pytest.mark.asyncio
async def test_handle_retryable_error_non_retryable():
    """Test handle_retryable_error with non-retryable error."""
    async def operation(attempt):
        raise ValueError("Test non-retryable error")

    with pytest.raises(InternalError) as exc_info:
        await handle_retryable_error(operation, "test context", max_attempts=3)
    assert "Non-retryable error" in str(exc_info.value)


@patch('src.utils.retry.retry_async', no_sleep_retry_async)
@pytest.mark.asyncio
async def test_handle_retryable_error_network_retry():
    """Test handle_retryable_error retries on network error."""
    call_count = 0

    async def operation(attempt):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise TimeoutError("Test network error")
        return "success", False

    result = await handle_retryable_error(operation, "test context", max_attempts=3)
    assert result == "success"
    assert call_count == 2


@patch('src.errors.handling.logging.error')
@patch('src.utils.retry.retry_async', no_sleep_retry_async)
@pytest.mark.asyncio
async def test_handle_retryable_error_custom_max(log_mock):
    """Test handle_retryable_error with custom max_attempts."""
    call_count = 0

    async def operation(attempt):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Test error")
        return "success", False

    result = await handle_retryable_error(operation, "test context", max_attempts=3)
    assert result == "success"
    assert call_count == 3
