from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp

from ..utils.retry import retry_async
from .internal import (
    InternalError,
    NetworkError,
    OAuthError,
    ParsingError,
    RateLimitError,
)

T = TypeVar("T")


def log_error(message: str, error: Exception) -> None:
    """Logs an error message with the associated exception details.

    This function formats and logs an error message along with the string
    representation of the exception using the logging module's error level.

    Args:
        message: A descriptive message about the error context.
        error: The exception instance to be logged.

    Returns:
        None

    Raises:
        No exceptions are raised by this function.
    """
    logging.error(f"Error: {message} - {str(error)}")


async def handle_api_error(operation: Callable[[], Awaitable[T]], context: str) -> T:
    """Handle API operations with standardized error handling.

    This function wraps an API operation, catches exceptions, logs them,
    and raises appropriate InternalError subclasses for consistent handling.

    Args:
        operation: The async API operation to execute.
        context: Descriptive context for the operation (e.g., "Twitch API call").

    Returns:
        The result of the operation if successful.

    Raises:
        InternalError subclasses: NetworkError, OAuthError, ParsingError, RateLimitError.
    """
    try:
        return await operation()
    except (aiohttp.ClientError, ValueError, RuntimeError, OSError, InternalError) as e:
        log_error(f"API error in {context}", e)
        if isinstance(e, asyncio.TimeoutError | ConnectionError):
            raise NetworkError(f"Network error in {context}: {str(e)}") from e
        elif hasattr(e, "status") and e.status == 401:  # Assuming aiohttp-like response
            raise OAuthError(f"Authentication error in {context}: {str(e)}") from e
        elif hasattr(e, "status") and e.status == 429:
            raise RateLimitError(f"Rate limit exceeded in {context}") from e
        elif hasattr(e, "status") and 400 <= e.status < 500:
            raise ParsingError(f"Client error in {context}: {str(e)}") from e
        else:
            raise InternalError(f"Unexpected error in {context}: {str(e)}") from e


async def handle_retryable_error(
    operation: Callable[[int], Awaitable[tuple[T, bool]]],
    context: str,
    max_attempts: int = 3,
) -> T:
    """Handle retryable operations with standardized retry logic.

    This function wraps a retryable operation using the retry utility,
    with logging and error categorization.

    Args:
        operation: Async callable that takes attempt number and returns (result, should_retry).
        context: Descriptive context for the operation.
        max_attempts: Maximum number of retry attempts.

    Returns:
        The result if successful, None if all retries exhausted.

    Raises:
        InternalError: If retries are exhausted and operation fails.
    """

    async def wrapped_operation(attempt: int) -> tuple[T, bool]:
        try:
            result, should_retry = await operation(attempt)
            return result, should_retry
        except (aiohttp.ClientError, ValueError, RuntimeError, OSError) as e:
            log_error(f"Retryable error in {context} (attempt {attempt + 1})", e)
            # Determine if retryable based on exception type
            if isinstance(e, NetworkError | asyncio.TimeoutError | ConnectionError):
                should_retry = attempt < max_attempts - 1
            else:
                should_retry = False
            if not should_retry:
                raise InternalError(
                    f"Non-retryable error in {context}: {str(e)}"
                ) from e
            return None, should_retry  # type: ignore

    result = await retry_async(wrapped_operation, max_attempts)
    if result is None:
        log_error(
            f"All retry attempts exhausted for {context}",
            RuntimeError("Retries exhausted"),
        )
        raise InternalError(f"Operation failed after retries in {context}")
    return result
