"""Unit and integration tests for src/utils/retry.py."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest

from src.utils.retry import retry_async


@pytest.mark.asyncio
async def test_retry_async_success_first_attempt():
    """Test successful operation on first attempt."""
    async def operation(attempt):
        await asyncio.sleep(0)
        return "success", False

    result = await retry_async(operation, max_attempts=3)
    assert result == "success"


@pytest.mark.asyncio
async def test_retry_async_success_after_retry():
    """Test successful operation after one retry."""
    call_count = 0

    async def operation(attempt):
        await asyncio.sleep(0)
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return None, True
        return "success", False

    result = await retry_async(operation, max_attempts=3)
    assert result == "success"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_async_failure_max_attempts():
    """Test failure after exhausting max attempts."""
    async def operation(attempt):
        await asyncio.sleep(0)
        return None, True

    result = await retry_async(operation, max_attempts=2)
    assert result is None


@pytest.mark.asyncio
async def test_retry_async_backoff_timing():
    """Test exponential backoff timing."""
    delays = []

    async def mock_sleep(delay): #noqa
        if delay > 0:
            delays.append(delay)

    async def operation(attempt): #noqa
        return None, True

    with patch('asyncio.sleep', side_effect=mock_sleep):
        await retry_async(operation, max_attempts=3, backoff_func=lambda a: 2 ** a)

    assert delays == [1, 2]  # Delays for attempt 0 and 1


@pytest.mark.asyncio
async def test_retry_async_max_attempts_reached():
    """Test that max attempts are not exceeded."""
    call_count = 0

    async def operation(attempt):
        await asyncio.sleep(0)
        nonlocal call_count
        call_count += 1
        return None, True

    result = await retry_async(operation, max_attempts=2)
    assert result is None
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_async_runtime_error():
    """Test handling of RuntimeError exception."""
    async def operation(attempt):
        await asyncio.sleep(0)
        if attempt == 0:
            raise RuntimeError("Test error")
        return "success", False

    result = await retry_async(operation, max_attempts=2)
    assert result == "success"


@pytest.mark.asyncio
async def test_retry_async_value_error():
    """Test handling of ValueError exception."""
    async def operation(attempt):
        await asyncio.sleep(0)
        if attempt == 0:
            raise ValueError("Test error")
        return "success", False

    result = await retry_async(operation, max_attempts=2)
    assert result == "success"


@pytest.mark.asyncio
async def test_retry_async_aiohttp_error():
    """Test handling of aiohttp.ClientError exception."""
    async def operation(attempt):
        await asyncio.sleep(0)
        if attempt == 0:
            raise aiohttp.ClientError("Test error")
        return "success", False

    result = await retry_async(operation, max_attempts=2)
    assert result == "success"
