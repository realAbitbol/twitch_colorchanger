from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Import structured logging
from ..logging_config import log_structured_error
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


def log_error(message: str, error: Exception, context: dict = None) -> None:
    """Logs an error message with the associated exception details.

    This function formats and logs an error message along with the string
    representation of the exception using structured logging for better
    error tracking and aggregation.

    Args:
        message: A descriptive message about the error context.
        error: The exception instance to be logged.
        context: Optional additional context data for debugging.

    Returns:
        None

    Raises:
        No exceptions are raised by this function.
    """
    # Determine error type from exception
    error_type = "unknown"
    if isinstance(error, NetworkError | OSError | ConnectionError):
        error_type = "network"
    elif isinstance(error, OAuthError):
        error_type = "auth"
    elif isinstance(error, RateLimitError):
        error_type = "ratelimit"
    elif isinstance(error, ParsingError):
        error_type = "parsing"
    elif isinstance(error, InternalError):
        error_type = "internal"

    # Use structured logging
    log_structured_error(
        error_type=error_type,
        message=f"{message}: {str(error)}",
        exception=error,
        context=context
    )


async def handle_api_error[T](operation: Callable[[], Awaitable[T]], context: str) -> T:  # type: ignore[valid-type]
    """Handle API operations with standardized error handling and actionable information.

    This function wraps an API operation, catches exceptions, logs them with
    structured context, and raises appropriate InternalError subclasses for
    consistent handling. Provides clear, actionable error messages for operators.

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
        # Build actionable context
        error_context = {"operation": context, "timestamp": time.time()}

        if hasattr(e, "status"):
            error_context["http_status"] = e.status
        if hasattr(e, "url"):
            error_context["url"] = str(e.url)

        log_error(f"API operation failed in {context}", e, context=error_context)

        if isinstance(e, OSError | ConnectionError):
            raise NetworkError(
                f"Network connectivity issue in {context}. Check internet connection and DNS resolution. Error: {str(e)}"
            ) from e
        elif hasattr(e, "status") and e.status == 401:
            raise OAuthError(
                f"Authentication failed in {context}. Token may be expired or invalid. Check token validity and refresh mechanism. Error: {str(e)}"
            ) from e
        elif hasattr(e, "status") and e.status == 429:
            raise RateLimitError(
                f"API rate limit exceeded in {context}. Implement backoff strategy or reduce request frequency."
            ) from e
        elif hasattr(e, "status") and 400 <= e.status < 500:
            raise ParsingError(
                f"Client error in {context} (HTTP {e.status}). Check request parameters and API documentation. Error: {str(e)}"
            ) from e
        else:
            raise InternalError(
                f"Unexpected error in {context}. This may indicate a bug or service issue. Error: {str(e)}"
            ) from e


def is_retryable_error(error: Exception) -> bool:
    """Check if an exception should trigger a retry."""
    return isinstance(
        error, RetryableOperationError | NetworkError | OSError | ConnectionError
    )


async def _execute_and_categorize_retryable_operation[T](  # type: ignore[valid-type]
    operation: Callable[[int], Awaitable[tuple[T | None, bool]]],
    attempt_count: int,
    context: str,
) -> T | None:
    try:
        result, should_retry = await operation(attempt_count)
        if not should_retry:
            return result
        raise RetryableOperationError(f"Operation indicated retry needed for {context}")
    except (aiohttp.ClientError, ValueError, RuntimeError, OSError, NetworkError) as e:
        if is_retryable_error(e):
            raise
        log_error(
            f"Non-retryable error in {context}",
            e,
            context={"attempt": attempt_count, "operation": context}
        )
        raise InternalError(f"Non-retryable error in {context}. This error cannot be resolved through retries and requires manual intervention. Error: {str(e)}") from e


async def handle_retryable_error[T](  # type: ignore[valid-type]
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
        if attempt_count > 1:
            logging.info(f"Retrying {context} (retry {attempt_count})")

    def after_retry(retry_state):
        if retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            log_error(
                f"Retry failed for {context} (attempt {attempt_count})",
                exception,
                context={"retry_attempt": attempt_count, "operation": context}
            )

    async def wrapped_operation() -> T | None:
        return await _execute_and_categorize_retryable_operation(
            operation, attempt_count, context
        )

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
        log_error(
            f"All retry attempts exhausted for {context}",
            e,
            context={"max_attempts": max_attempts, "operation": context}
        )
        raise InternalError(
            f"Operation failed after {max_attempts} retries in {context}. This indicates a persistent issue that requires investigation. Error: {str(e)}"
        ) from e
