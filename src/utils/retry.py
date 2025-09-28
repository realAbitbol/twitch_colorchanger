"""Retry utilities for asynchronous operations using Tenacity."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


class RetryableException(Exception):
    """Exception raised to indicate an operation should be retried."""

    pass


class RetryExhaustedError(Exception):
    """Exception raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, attempts: int, final_exception: Exception | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.final_exception = final_exception


async def retry_async[T](  # type: ignore[valid-type]
    operation: Callable[[int], Awaitable[tuple[T | None, bool]]],
    max_attempts: int = 6,
) -> T:
    """Retry an asynchronous operation with exponential backoff using Tenacity.

    Args:
        operation: Async callable that takes attempt number and returns (result, should_retry).
        max_attempts: Maximum number of attempts.

    Returns:
        The result from operation if successful.

    Raises:
        RetryExhaustedError: If all attempts are exhausted.
    """
    attempt_count = 0

    def before_retry(retry_state):
        nonlocal attempt_count
        attempt_count = retry_state.attempt_number

    async def wrapped_operation() -> T | None:
        try:
            result, should_retry = await operation(attempt_count)
            if not should_retry:
                return result
            # If should_retry is True, raise exception to trigger retry
            raise RetryableException("Operation indicated retry is needed")
        except (RuntimeError, ValueError, OSError, aiohttp.ClientError) as e:
            # For caught exceptions, always retry if attempts remain
            raise RetryableException("Exception occurred, retrying") from e

    # Use Tenacity's AsyncRetrying with built-in exponential backoff
    retrying = AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, max=60),  # Built-in exponential backoff
        retry=retry_if_exception_type(RetryableException),
        before=before_retry,
    )

    try:
        return await retrying(wrapped_operation)
    except Exception as e:
        # All attempts exhausted
        raise RetryExhaustedError(
            f"Operation failed after {max_attempts} attempts",
            attempts=max_attempts,
            final_exception=e,
        ) from e
