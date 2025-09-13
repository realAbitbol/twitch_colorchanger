"""Retry utilities for asynchronous operations."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp

T = TypeVar("T")


async def retry_async(
    operation: Callable[[int], Awaitable[tuple[T, bool]]],
    max_attempts: int = 6,
    backoff_func: Callable[[int], float] = lambda attempt: min(1 * (2**attempt), 60),
) -> T | None:
    """Retry an asynchronous operation with exponential backoff.

    Args:
        operation: Async callable that takes attempt number and returns (result, should_retry).
        max_attempts: Maximum number of attempts.
        backoff_func: Function to calculate delay based on attempt number.

    Returns:
        The result from operation if successful, None if all attempts exhausted.
    """
    for attempt in range(max_attempts):
        try:
            result, should_retry = await operation(attempt)
            if not should_retry:
                return result
        except (RuntimeError, ValueError, OSError, aiohttp.ClientError):
            should_retry = attempt < max_attempts - 1
            if not should_retry:
                raise
        if attempt < max_attempts - 1:
            await asyncio.sleep(backoff_func(attempt))

    return None
