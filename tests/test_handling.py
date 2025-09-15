from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientResponseError

from src.errors.handling import (
    RetryableOperationError,
    _execute_and_categorize_retryable_operation,
    handle_api_error,
    handle_retryable_error,
    is_retryable_error,
)
from src.errors.internal import (
    InternalError,
    NetworkError,
    OAuthError,
    ParsingError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_handle_api_error_network_exception():
    """Test handle_api_error raises NetworkError for network exceptions."""
    async def failing_operation():
        raise OSError("Network error")

    with pytest.raises(NetworkError):
        await handle_api_error(failing_operation, "test context")


@pytest.mark.asyncio
async def test_handle_api_error_oauth_error():
    """Test handle_api_error raises OAuthError for 401 status."""
    mock_request = MagicMock()
    mock_request.real_url = "http://test.com"
    async def failing_operation():
        raise ClientResponseError(mock_request, (), status=401)

    with pytest.raises(OAuthError):
        await handle_api_error(failing_operation, "test context")


@pytest.mark.asyncio
async def test_handle_api_error_rate_limit():
    """Test handle_api_error raises RateLimitError for 429 status."""
    mock_request = MagicMock()
    mock_request.real_url = "http://test.com"
    async def failing_operation():
        raise ClientResponseError(mock_request, (), status=429)

    with pytest.raises(RateLimitError):
        await handle_api_error(failing_operation, "test context")


@pytest.mark.asyncio
async def test_handle_api_error_parsing_error():
    """Test handle_api_error raises ParsingError for 4xx status."""
    mock_request = MagicMock()
    mock_request.real_url = "http://test.com"
    async def failing_operation():
        raise ClientResponseError(mock_request, (), status=400)

    with pytest.raises(ParsingError):
        await handle_api_error(failing_operation, "test context")


@pytest.mark.asyncio
async def test_handle_retryable_error_max_attempts():
    """Test handle_retryable_error exhausts retries after max attempts."""
    async def failing_operation(attempt):
        logging.info("failing_operation called with attempt: %s", attempt)
        await asyncio.sleep(0)  # Use async feature to satisfy linter
        return None, True  # Always retry

    with pytest.raises(InternalError):
        await handle_retryable_error(failing_operation, "test context", max_attempts=2)


@pytest.mark.asyncio
async def test_handle_retryable_error_non_retryable_error():
    """Test handle_retryable_error handles non-retryable errors."""
    async def failing_operation(attempt):
        raise ValueError("Non-retryable")

    with pytest.raises(InternalError):
        await handle_retryable_error(failing_operation, "test context")


@pytest.mark.asyncio
async def test_execute_and_categorize_retryable_operation_retry_indicated():
    """Test _execute_and_categorize_retryable_operation when retry indicated."""
    async def operation(attempt):
        await asyncio.sleep(0)  # Use async feature to satisfy linter
        return "result", True

    with pytest.raises(RetryableOperationError):
        await _execute_and_categorize_retryable_operation(operation, 1, "test")

    # Actually, the function raises RetryableOperationError when should_retry is True
    with pytest.raises(RetryableOperationError):
        await _execute_and_categorize_retryable_operation(operation, 1, "test")


def test_is_retryable_error_custom_exception():
    """Test is_retryable_error with custom exception."""
    error = RetryableOperationError("test")
    assert is_retryable_error(error) is True

    error = ValueError("test")
    assert is_retryable_error(error) is False
