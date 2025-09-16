"""Comprehensive tests for EventSub error hierarchy.

Tests cover inheritance verification, context preservation, and exception behavior.
"""

import pytest

from src.errors.eventsub import (
    AuthenticationError,
    CacheError,
    EventSubConnectionError,
    EventSubError,
    MessageProcessingError,
    SubscriptionError,
)


class TestEventSubErrorHierarchy:
    """Test the EventSub error hierarchy structure and inheritance."""

    def test_inheritance_chain(self):
        """Verify the inheritance chain for all exception types."""
        # Test that all exceptions inherit from EventSubError
        assert issubclass(EventSubConnectionError, EventSubError)
        assert issubclass(SubscriptionError, EventSubError)
        assert issubclass(AuthenticationError, EventSubError)
        assert issubclass(MessageProcessingError, EventSubError)
        assert issubclass(CacheError, EventSubError)

        # Test that EventSubError inherits from Exception
        assert issubclass(EventSubError, Exception)

    def test_exception_instances_are_instances_of_base(self):
        """Verify that exception instances are instances of the base class."""
        conn_err = EventSubConnectionError("test")
        sub_err = SubscriptionError("test")
        auth_err = AuthenticationError("test")
        msg_err = MessageProcessingError("test")
        cache_err = CacheError("test")

        assert isinstance(conn_err, EventSubError)
        assert isinstance(sub_err, EventSubError)
        assert isinstance(auth_err, EventSubError)
        assert isinstance(msg_err, EventSubError)
        assert isinstance(cache_err, EventSubError)

        # All should be instances of Exception
        assert isinstance(conn_err, Exception)
        assert isinstance(sub_err, Exception)
        assert isinstance(auth_err, Exception)
        assert isinstance(msg_err, Exception)
        assert isinstance(cache_err, Exception)


class TestEventSubErrorContext:
    """Test context parameter preservation in exceptions."""

    def test_base_exception_context_preservation(self):
        """Test that EventSubError preserves context parameters."""
        err = EventSubError(
            "Test error",
            request_id="req-123",
            user_id="user-456",
            operation_type="test_op"
        )

        assert err.request_id == "req-123"
        assert err.user_id == "user-456"
        assert err.operation_type == "test_op"
        assert str(err) == "Test error"

    def test_connection_error_context(self):
        """Test EventSubConnectionError context preservation."""
        err = EventSubConnectionError(
            "Connection failed",
            request_id="req-789",
            user_id="user-101",
            operation_type="connect"
        )

        assert err.request_id == "req-789"
        assert err.user_id == "user-101"
        assert err.operation_type == "connect"
        assert str(err) == "Connection failed"

    def test_subscription_error_context(self):
        """Test SubscriptionError context preservation."""
        err = SubscriptionError(
            "Subscription failed",
            request_id="req-sub",
            user_id="user-sub",
            operation_type="subscribe"
        )

        assert err.request_id == "req-sub"
        assert err.user_id == "user-sub"
        assert err.operation_type == "subscribe"

    def test_authentication_error_context(self):
        """Test AuthenticationError context preservation."""
        err = AuthenticationError(
            "Auth failed",
            request_id="req-auth",
            user_id="user-auth",
            operation_type="validate_token"
        )

        assert err.request_id == "req-auth"
        assert err.user_id == "user-auth"
        assert err.operation_type == "validate_token"

    def test_message_processing_error_context(self):
        """Test MessageProcessingError context preservation."""
        err = MessageProcessingError(
            "Processing failed",
            request_id="req-msg",
            user_id="user-msg",
            operation_type="parse_json"
        )

        assert err.request_id == "req-msg"
        assert err.user_id == "user-msg"
        assert err.operation_type == "parse_json"

    def test_cache_error_context(self):
        """Test CacheError context preservation."""
        err = CacheError(
            "Cache error",
            request_id="req-cache",
            user_id="user-cache",
            operation_type="load_cache"
        )

        assert err.request_id == "req-cache"
        assert err.user_id == "user-cache"
        assert err.operation_type == "load_cache"

    def test_optional_context_parameters(self):
        """Test that context parameters are optional."""
        # Test with no context
        err1 = EventSubError("No context")
        assert err1.request_id is None
        assert err1.user_id is None
        assert err1.operation_type is None

        # Test with partial context
        err2 = EventSubError("Partial context", request_id="req-only")
        assert err2.request_id == "req-only"
        assert err2.user_id is None
        assert err2.operation_type is None

    def test_exception_raising_with_context(self):
        """Test that exceptions can be raised and caught with context."""
        with pytest.raises(EventSubConnectionError) as exc_info:
            raise EventSubConnectionError(
                "Test raise",
                request_id="raise-req",
                user_id="raise-user",
                operation_type="raise-op"
            )

        err = exc_info.value
        assert err.request_id == "raise-req"
        assert err.user_id == "raise-user"
        assert err.operation_type == "raise-op"
        assert str(err) == "Test raise"


class TestExceptionBehavior:
    """Test general exception behavior."""

    def test_exception_messages(self):
        """Test that exception messages are properly set."""
        messages = [
            ("Connection error", EventSubConnectionError),
            ("Subscription error", SubscriptionError),
            ("Auth error", AuthenticationError),
            ("Message error", MessageProcessingError),
            ("Cache error", CacheError),
        ]

        for msg, exc_class in messages:
            err = exc_class(msg)
            assert str(err) == msg

    def test_exception_inheritance_in_catch_blocks(self):
        """Test that exceptions can be caught as base class."""
        def raise_connection_error():
            raise EventSubConnectionError("Connection failed")

        def raise_auth_error():
            raise AuthenticationError("Auth failed")

        # Should catch as EventSubError
        with pytest.raises(EventSubError):
            raise_connection_error()

        with pytest.raises(EventSubError):
            raise_auth_error()

        # Should catch as Exception
        with pytest.raises(EventSubError):
            raise_connection_error()

    def test_context_inheritance(self):
        """Test that context is preserved through inheritance."""
        # Create a connection error with context
        err = EventSubConnectionError(
            "Inherited context",
            request_id="inherit-req",
            user_id="inherit-user",
            operation_type="inherit-op"
        )

        # Since it inherits from EventSubError, context should be accessible
        assert err.request_id == "inherit-req"
        assert err.user_id == "inherit-user"


        assert err.operation_type == "inherit-op"
