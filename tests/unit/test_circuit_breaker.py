"""
Unit Test for Circuit Breaker

Tests the circuit breaker functionality, including concurrent calls to verify reduced lock contention.
"""

import asyncio
import time
import pytest
from unittest.mock import patch

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    CircuitBreakerState,
    get_circuit_breaker,
    reset_circuit_breaker,
    get_circuit_breaker_state,
    remove_circuit_breaker,
    cleanup_circuit_breakers,
    _circuit_breakers,
)


class TestCircuitBreaker:
    """Test class for CircuitBreaker functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.config = CircuitBreakerConfig(name="test", failure_threshold=2, recovery_timeout=1.0)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_should_allow_calls_in_closed_state(self):
        """Test that calls are allowed when circuit breaker is in CLOSED state."""
        # Arrange
        cb = CircuitBreaker(self.config)
        call_count = 0

        async def dummy_func():
            nonlocal call_count
            call_count += 1
            return "success"

        # Act
        result = await cb.call(dummy_func)

        # Assert
        assert result == "success"
        assert call_count == 1
        assert cb.is_closed

    @pytest.mark.asyncio
    async def test_should_open_after_failure_threshold(self):
        """Test that circuit breaker opens after reaching failure threshold."""
        # Arrange
        cb = CircuitBreaker(self.config)

        async def failing_func():
            raise ValueError("Test failure")

        # Act & Assert
        with pytest.raises(ValueError):
            await cb.call(failing_func)

        with pytest.raises(ValueError):
            await cb.call(failing_func)

        # Should be open now
        with pytest.raises(CircuitBreakerOpenException):
            await cb.call(lambda: "should not call")

        assert cb.is_open

    @pytest.mark.asyncio
    async def test_should_attempt_recovery_after_timeout(self):
        """Test that circuit breaker attempts recovery after recovery timeout."""
        # Arrange
        config = CircuitBreakerConfig(name="test", failure_threshold=1, recovery_timeout=0.1, success_threshold=1)
        cb = CircuitBreaker(config)

        async def failing_func():
            raise ValueError("Test failure")

        # Act - Fail once to open
        with pytest.raises(ValueError):
            await cb.call(failing_func)

        assert cb.is_open

        # Wait for recovery timeout
        await asyncio.sleep(0.2)

        # Should attempt recovery (transition to HALF_OPEN)
        async def success_func():
            return "recovered"

        result = await cb.call(success_func)

        # Assert
        assert result == "recovered"
        assert cb.is_closed  # Should be closed after success

    @pytest.mark.asyncio
    async def test_should_handle_concurrent_calls_without_blocking(self):
        """Test that concurrent calls execute without lock contention during function execution."""
        # Arrange
        cb = CircuitBreaker(self.config)
        execution_times = []

        async def slow_func(delay: float):
            start = time.monotonic()
            await asyncio.sleep(delay)
            end = time.monotonic()
            execution_times.append((start, end))
            return f"completed after {delay}s"

        # Act - Run multiple concurrent calls
        start_time = time.monotonic()
        results = await asyncio.gather(
            cb.call(slow_func, 0.1),
            cb.call(slow_func, 0.1),
            cb.call(slow_func, 0.1),
        )
        end_time = time.monotonic()

        # Assert
        # All calls should succeed
        assert len(results) == 3
        assert all("completed" in r for r in results)

        # Total time should be close to the longest individual delay (not sum)
        # If blocked, it would take ~0.3s, but concurrent should take ~0.1s
        total_duration = end_time - start_time
        assert total_duration < 0.2  # Should be much less than 0.3 if concurrent

        # Circuit breaker should still be closed
        assert cb.is_closed

    @pytest.mark.asyncio
    async def test_should_maintain_thread_safety_during_state_updates(self):
        """Test that state updates remain thread-safe despite reduced lock time."""
        # Arrange - Use higher failure threshold to allow all calls to execute
        config = CircuitBreakerConfig(name="test", failure_threshold=6, recovery_timeout=1.0)
        cb = CircuitBreaker(config)
        success_count = 0
        failure_count = 0

        async def sometimes_failing_func(should_fail: bool):
            nonlocal success_count, failure_count
            if should_fail:
                failure_count += 1
                raise ValueError("Simulated failure")
            else:
                success_count += 1
                return "success"

        # Act - Mix of successes and failures
        tasks = []
        for i in range(10):
            should_fail = i < 5  # First 5 fail, next 5 succeed
            tasks.append(cb.call(sometimes_failing_func, should_fail))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Assert
        # Should have 5 failures and 5 successes
        exceptions = [r for r in results if isinstance(r, Exception)]
        successes = [r for r in results if not isinstance(r, Exception)]

        assert len(exceptions) == 5
        assert len(successes) == 5
        assert success_count == 5
        assert failure_count == 5

        # Circuit breaker should be open due to failures (5 >= 6? No, 5 < 6, so closed)
        assert cb.is_closed


class TestGlobalCircuitBreakerRegistry:
    """Test class for global circuit breaker registry functions."""

    def teardown_method(self):
        """Teardown method called after each test to clear global registry."""
        _circuit_breakers.clear()

    def test_should_create_circuit_breaker_with_default_config(self):
        """Test that get_circuit_breaker creates a circuit breaker with default config."""
        # Act
        cb = get_circuit_breaker("test_default")

        # Assert
        assert cb is not None
        assert cb.config.name == "test_default"
        assert cb.config.failure_threshold == 5
        assert cb.config.recovery_timeout == 300.0
        assert cb.config.success_threshold == 3

    def test_should_create_circuit_breaker_with_custom_config(self):
        """Test that get_circuit_breaker uses provided config."""
        # Arrange
        config = CircuitBreakerConfig(name="test_custom", failure_threshold=10, recovery_timeout=600.0)

        # Act
        cb = get_circuit_breaker("test_custom", config)

        # Assert
        assert cb.config.name == "test_custom"
        assert cb.config.failure_threshold == 10
        assert cb.config.recovery_timeout == 600.0

    def test_should_return_same_instance_for_same_name(self):
        """Test that get_circuit_breaker implements singleton pattern."""
        # Act
        cb1 = get_circuit_breaker("singleton_test")
        cb2 = get_circuit_breaker("singleton_test")

        # Assert
        assert cb1 is cb2

    def test_should_reset_existing_circuit_breaker(self):
        """Test that reset_circuit_breaker resets an existing circuit breaker."""
        # Arrange
        cb = get_circuit_breaker("reset_test")
        # Simulate some state changes
        cb.failure_count = 2
        cb.state = CircuitBreakerState.OPEN

        # Act
        reset_circuit_breaker("reset_test")

        # Assert
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time is None

    def test_should_handle_reset_nonexistent_circuit_breaker(self):
        """Test that reset_circuit_breaker handles non-existent circuit breakers gracefully."""
        # Act - Should not raise exception
        reset_circuit_breaker("nonexistent")

        # Assert - No exception raised, registry remains empty
        assert len(_circuit_breakers) == 0

    def test_should_get_circuit_breaker_state_for_existing_breaker(self):
        """Test that get_circuit_breaker_state returns correct state for existing breaker."""
        # Arrange
        cb = get_circuit_breaker("state_test")
        cb.state = CircuitBreakerState.OPEN

        # Act
        state = get_circuit_breaker_state("state_test")

        # Assert
        assert state == "open"

    def test_should_return_none_for_nonexistent_circuit_breaker_state(self):
        """Test that get_circuit_breaker_state returns None for non-existent breaker."""
        # Act
        state = get_circuit_breaker_state("nonexistent")

        # Assert
        assert state is None

    def test_should_remove_existing_circuit_breaker(self):
        """Test that remove_circuit_breaker removes an existing circuit breaker."""
        # Arrange
        get_circuit_breaker("remove_test")

        # Act
        remove_circuit_breaker("remove_test")

        # Assert
        assert "remove_test" not in _circuit_breakers

    def test_should_handle_remove_nonexistent_circuit_breaker(self):
        """Test that remove_circuit_breaker handles non-existent circuit breakers gracefully."""
        # Act - Should not raise exception
        remove_circuit_breaker("nonexistent")

        # Assert - No exception raised, registry remains empty
        assert len(_circuit_breakers) == 0

    @patch('src.utils.circuit_breaker.time.monotonic')
    def test_should_cleanup_inactive_circuit_breakers(self, mock_monotonic):
        """Test that cleanup_circuit_breakers removes inactive breakers."""
        # Arrange
        mock_monotonic.return_value = 4000.0  # Current time

        # Create breakers with different last_used times
        cb1 = get_circuit_breaker("active")
        cb1.last_used = 3500.0  # Used recently (within 1 hour: 4000 - 3500 = 500 < 3600)

        cb2 = get_circuit_breaker("inactive")
        cb2.last_used = 100.0  # Used long ago (over 1 hour: 4000 - 100 = 3900 > 3600)

        cb3 = get_circuit_breaker("very_inactive")
        cb3.last_used = 50.0  # Also over 1 hour ago (4000 - 50 = 3950 > 3600)

        # Act
        removed_count = cleanup_circuit_breakers()

        # Assert
        assert removed_count == 2
        assert "active" in _circuit_breakers
        assert "inactive" not in _circuit_breakers
        assert "very_inactive" not in _circuit_breakers

    @patch('src.utils.circuit_breaker.time.monotonic')
    def test_should_not_cleanup_recently_used_breakers(self, mock_monotonic):
        """Test that cleanup_circuit_breakers preserves recently used breakers."""
        # Arrange
        mock_monotonic.return_value = 1000.0  # Current time

        # Create breakers all used recently
        cb1 = get_circuit_breaker("recent1")
        cb1.last_used = 950.0  # Within 1 hour

        cb2 = get_circuit_breaker("recent2")
        cb2.last_used = 980.0  # Within 1 hour

        # Act
        removed_count = cleanup_circuit_breakers()

        # Assert
        assert removed_count == 0
        assert "recent1" in _circuit_breakers
        assert "recent2" in _circuit_breakers

    @patch('src.utils.circuit_breaker.time.monotonic')
    def test_should_return_zero_when_no_breakers_to_cleanup(self, mock_monotonic):
        """Test that cleanup_circuit_breakers returns 0 when no breakers are inactive."""
        # Arrange
        mock_monotonic.return_value = 1000.0

        # No breakers created

        # Act
        removed_count = cleanup_circuit_breakers()

        # Assert
        assert removed_count == 0