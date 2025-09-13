"""Centralized internal error hierarchy.

These exceptions provide semantic categories for retry logic and higher-level
error handling. Only raise these inside application/network boundaries – never
directly surface raw aiohttp / JSON errors to retry code; wrap them instead.

Classes:
  InternalError        – Base for all internal errors.
  NetworkError         – Transient network/IO issues (safe to retry).
  OAuthError           – Authentication / authorization related failures.
  ParsingError         – Response parsing / schema validation issues.
  RateLimitError       – Explicit rate limiting signalled by remote service.

Each subclass sets the transient flag indicating whether automated retry
policies should consider another attempt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class InternalError(Exception):
    """Base class for all internal application errors with metadata support.

    This exception provides a foundation for categorizing errors within the
    application, including optional structured metadata and a transience flag
    to indicate whether the error is suitable for automatic retry.

    Attributes:
        transient: Boolean indicating if the error is transient and may be retried.
        data: Dictionary containing arbitrary structured context data.

    Args:
        message: Descriptive error message.
        data: Optional mapping of additional context data.

    Raises:
        No specific exceptions raised beyond standard Exception behavior.
    """

    transient: bool = False  # Override in subclasses if appropriate
    data: dict[str, object]

    def __init__(
        self, message: str, *, data: Mapping[str, object] | None = None
    ) -> None:
        """Initialize the InternalError with message and optional data.

        Args:
            message: The error message to be displayed.
            data: Optional dictionary of additional context data. If provided,
                it will be copied to prevent mutations.

        Returns:
            None
        """
        super().__init__(message)
        # Copy into a plain dict to avoid unexpected mutations from caller.
        self.data = dict(data) if data else {}


class NetworkError(InternalError):
    """Exception raised for network or transport layer errors.

    This includes issues such as connection timeouts, resets, or other
    transient network failures that may be retried.

    Attributes:
        transient: Always True, indicating this error is suitable for retry.
    """

    transient = True


class OAuthError(InternalError):
    """Exception raised for OAuth authentication or authorization failures.

    These errors typically indicate issues with credentials, tokens, or
    permissions that are not suitable for automatic retry.

    Attributes:
        transient: Always False, indicating this error should not be retried.
    """

    transient = False


class ParsingError(InternalError):
    """Exception raised for response parsing or schema validation errors.

    This includes issues with JSON parsing, unexpected data formats, or
    schema mismatches that typically cannot be resolved through retry.

    Attributes:
        transient: Always False, indicating this error should not be retried.
    """

    transient = False


@dataclass
class RateLimitContext:
    """Context information for rate limiting errors.

    This dataclass holds details about the current rate limit state,
    such as the number of remaining requests allowed.

    Attributes:
        remaining: The number of remaining requests allowed, or None if unknown.
    """

    remaining: int | None = None


class RateLimitError(InternalError):
    """Exception raised when rate limiting is encountered.

    This error indicates that the application has exceeded the allowed
    request rate and may be retried after a delay. The transient flag
    is set to allow retry strategies to apply backoff.

    Attributes:
        transient: Always True, indicating this error may be retried.

    Args:
        message: Optional error message, defaults to "Rate limited".
        context: Optional RateLimitContext with additional rate limit details.

    Raises:
        No specific exceptions raised beyond standard Exception behavior.
    """

    transient = True

    def __init__(
        self, message: str = "Rate limited", *, context: RateLimitContext | None = None
    ):
        """Initialize the RateLimitError with message and optional context.

        Args:
            message: The error message, defaults to "Rate limited".
            context: Optional context information about the rate limit state.

        Returns:
            None
        """
        super().__init__(message, data={"rate_limit": context})


__all__ = [
    "InternalError",
    "NetworkError",
    "OAuthError",
    "ParsingError",
    "RateLimitError",
    "RateLimitContext",
]
