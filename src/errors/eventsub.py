"""EventSub error hierarchy for Twitch EventSub backend operations.

This module defines a hierarchy of exceptions specific to EventSub-related errors,
following Python exception best practices with clear inheritance and descriptive docstrings.

All exceptions support additional context parameters for better error tracking and debugging.
"""


class EventSubError(Exception):
    """Base exception for all EventSub-related errors.

    This is the root exception class for the EventSub error hierarchy.
    All EventSub-specific exceptions should inherit from this class.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'connect', 'subscribe').

    Example:
        >>> raise EventSubError("Generic error", request_id="req-123", user_id="user-456", operation_type="connect")
    """

    def __init__(
        self,
        message: str,
        request_id: str | None = None,
        user_id: str | None = None,
        operation_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.user_id = user_id
        self.operation_type = operation_type


class EventSubConnectionError(EventSubError):
    """Raised when there are connection-related issues with EventSub.

    This exception is raised when the EventSub backend fails to establish,
    maintain, or close connections to the Twitch EventSub service.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'connect', 'reconnect').

    Example:
        >>> raise EventSubConnectionError("Failed to connect to WebSocket", request_id="req-123", user_id="user-456", operation_type="connect")
    """

    pass


class SubscriptionError(EventSubError):
    """Raised when there are subscription-related issues with EventSub.

    This exception is raised when operations involving EventSub subscriptions
    fail, such as creating, updating, or deleting subscriptions.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'subscribe', 'unsubscribe').

    Example:
        >>> raise SubscriptionError("Subscription failed", request_id="req-123", user_id="user-456", operation_type="subscribe")
    """

    pass


class AuthenticationError(EventSubError):
    """Raised when there are authentication-related issues with EventSub.

    This exception is raised when authentication fails for EventSub operations,
    such as invalid or expired tokens.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'validate_token', 'authenticate').

    Example:
        >>> raise AuthenticationError("Token expired", request_id="req-123", user_id="user-456", operation_type="validate_token")
    """

    pass


class MessageProcessingError(EventSubError):
    """Raised when there are message processing issues with EventSub.

    This exception is raised when incoming EventSub messages cannot be
    processed correctly, such as malformed data or processing failures.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'process_message', 'parse_json').

    Example:
        >>> raise MessageProcessingError("Invalid JSON in message", request_id="req-123", user_id="user-456", operation_type="parse_json")
    """

    pass


class CacheError(EventSubError):
    """Raised when there are cache-related issues with EventSub.

    This exception is raised when operations involving the EventSub cache
    fail, such as cache misses, corruption, or persistence errors.

    Args:
        message (str): Error message.
        request_id (str | None): Optional request ID for tracking.
        user_id (str | None): Optional user ID associated with the error.
        operation_type (str | None): Optional operation type (e.g., 'load_cache', 'save_cache').

    Example:
        >>> raise CacheError("Cache file corrupted", request_id="req-123", user_id="user-456", operation_type="load_cache")
    """

    pass
