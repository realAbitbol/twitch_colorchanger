from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .internal import (
    InternalError,
    NetworkError,
    OAuthError,
    ParsingError,
    RateLimitError,
)


class RetryableOperationError(Exception):
    """Exception raised to indicate an operation should be retried."""

    pass


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


async def handle_api_error[T](operation: Callable[[], Awaitable[T]], context: str) -> T:
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
        if isinstance(e, OSError | ConnectionError):
            raise NetworkError(f"Network error in {context}: {str(e)}") from e
        elif hasattr(e, "status") and e.status == 401:
            raise OAuthError(f"Authentication error in {context}: {str(e)}") from e
        elif hasattr(e, "status") and e.status == 429:
            raise RateLimitError(f"Rate limit exceeded in {context}") from e
        elif hasattr(e, "status") and 400 <= e.status < 500:
            raise ParsingError(f"Client error in {context}: {str(e)}") from e
        else:
            raise InternalError(f"Unexpected error in {context}: {str(e)}") from e


async def handle_retryable_error[T](
    operation: Callable[[int], Awaitable[tuple[T | None, bool]]],
    context: str,
    max_attempts: int = 3,
) -> T:
    """Handle retryable operations with Tenacity-based retry logic.

    This function wraps a retryable operation using Tenacity's AsyncRetrying,
    with enhanced logging, statistics, and error categorization.

    Args:
        operation: Async callable that takes attempt number and returns (result, should_retry).
        context: Descriptive context for the operation.
        max_attempts: Maximum number of retry attempts.

    Returns:
        The result if successful.

    Raises:
        InternalError: If retries are exhausted and operation fails.
    """
    attempt_count = 0

    def before_retry(retry_state):
        nonlocal attempt_count
        attempt_count = retry_state.attempt_number
        logging.info(f"Retrying {context} (attempt {attempt_count})")

    def after_retry(retry_state):
        if retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            log_error(
                f"Retry failed for {context} (attempt {attempt_count})", exception
            )

    async def wrapped_operation() -> T | None:
        try:
            result, should_retry = await operation(attempt_count)
            if not should_retry:
                return result
            # Raise custom exception to trigger retry
            raise RetryableOperationError(
                f"Operation indicated retry needed for {context}"
            )
        except (aiohttp.ClientError, ValueError, RuntimeError, OSError) as e:
            # Categorize the error
            if isinstance(e, NetworkError | OSError | ConnectionError):
                raise  # Retryable
            else:
                # Non-retryable
                log_error(f"Non-retryable error in {context}", e)
                raise InternalError(
                    f"Non-retryable error in {context}: {str(e)}"
                ) from e

    retrying = AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, max=60),
        retry=retry_if_exception_type(
            (RetryableOperationError, NetworkError, OSError, ConnectionError)
        ),
        before=before_retry,
        after=after_retry,
    )

    try:
        result = await retrying(wrapped_operation)
        if result is None:
            raise InternalError(f"Operation returned None for {context}")
        return result
    except Exception as e:
        if isinstance(e, InternalError):
            raise
        log_error(f"All retry attempts exhausted for {context}", e)
        raise InternalError(
            f"Operation failed after retries in {context}: {str(e)}"
        ) from e
