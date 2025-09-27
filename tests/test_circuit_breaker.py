"""Tests for circuit breaker functionality."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    CircuitBreakerState,
    cleanup_circuit_breakers,
    get_circuit_breaker,
    get_circuit_breaker_state,
    remove_circuit_breaker,
    reset_circuit_breaker,
)


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig functionality."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 300.0  # 5 minutes for unattended operation
        assert config.success_threshold == 3
        assert config.name == "default"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=30.0,
            success_threshold=5,
            name="test_circuit",
        )
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 30.0
        assert config.success_threshold == 5
        assert config.name == "test_circuit"


class TestCircuitBreaker:
    """Test CircuitBreaker functionality."""

    def test_initial_state(self):
        """Test circuit breaker initializes in closed state."""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker(config)

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time is None
        assert not cb.is_open
        assert cb.is_closed
        assert not cb.is_half_open

    def test_successful_call_in_closed_state(self):
        """Test successful function call in closed state."""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker(config)

        result = "success"

        async def successful_function():
            return result

        async def test_call():
            return await cb.call(successful_function)

        # Should return the result and stay closed
        assert asyncio.run(test_call()) == result
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    def test_failure_threshold_reached(self):
        """Test circuit breaker opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=0.1)
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def test_failures():
            for i in range(3):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

        # After 3 failures, circuit should be open
        asyncio.run(test_failures())
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.failure_count == 3

    def test_circuit_open_exception(self):
        """Test CircuitBreakerOpenException is raised when circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0)
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def test_open_circuit():
            # Cause 2 failures to open circuit
            for i in range(2):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            # Next call should raise CircuitBreakerOpenException
            with pytest.raises(CircuitBreakerOpenException):
                await cb.call(lambda: "should not execute")

        asyncio.run(test_open_circuit())
        assert cb.is_open

    def test_half_open_transition(self):
        """Test transition from open to half-open after recovery timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def successful_function():
            return "success"

        async def test_recovery():
            # Cause failures to open circuit
            for i in range(2):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            assert cb.is_open

            # Wait for recovery timeout
            await asyncio.sleep(0.15)

            # Next call should transition to half-open
            result = await cb.call(successful_function)
            assert result == "success"
            assert cb.is_half_open
            assert cb.success_count == 1

        asyncio.run(test_recovery())

    def test_full_recovery_to_closed(self):
        """Test full recovery from half-open to closed state."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def successful_function():
            return "success"

        async def test_full_recovery():
            # Cause failures to open circuit
            for i in range(2):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            assert cb.is_open

            # Wait for recovery timeout
            await asyncio.sleep(0.15)

            # Make successful calls to reach success threshold
            for i in range(2):
                result = await cb.call(successful_function)
                assert result == "success"

            # Should be back to closed state
            assert cb.is_closed
            assert cb.success_count == 0  # Reset after recovery
            assert cb.failure_count == 0  # Reset after recovery

        asyncio.run(test_full_recovery())

    def test_failure_in_half_open_returns_to_open(self):
        """Test failure in half-open state returns to open."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def successful_function():
            return "success"

        async def test_half_open_failure():
            # Cause failures to open circuit
            for i in range(2):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            assert cb.is_open

            # Wait for recovery timeout
            await asyncio.sleep(0.15)

            # First successful call transitions to half-open
            await cb.call(successful_function)
            assert cb.is_half_open

            # Failure in half-open should return to open
            with pytest.raises(ValueError):
                await cb.call(failing_function)

            assert cb.is_open

        asyncio.run(test_half_open_failure())

    def test_sync_function_call(self):
        """Test circuit breaker works with synchronous functions."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(config)

        def sync_function():
            return "sync_result"

        async def test_sync():
            result = await cb.call(sync_function)
            return result

        assert asyncio.run(test_sync()) == "sync_result"
        assert cb.is_closed

    def test_manual_reset(self):
        """Test manual circuit breaker reset."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(config)

        async def failing_function():
            raise ValueError("Test error")

        async def test_reset():
            # Cause failures to open circuit
            for i in range(2):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            assert cb.is_open

            # Manual reset
            cb._reset()

            assert cb.is_closed
            assert cb.failure_count == 0
            assert cb.success_count == 0

        asyncio.run(test_reset())


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration functions."""

    def test_get_circuit_breaker_creates_new(self):
        """Test get_circuit_breaker creates new instance."""
        config = CircuitBreakerConfig(name="test_cb", failure_threshold=3)
        cb = get_circuit_breaker("test_cb", config)

        assert isinstance(cb, CircuitBreaker)
        assert cb.config.name == "test_cb"
        assert cb.config.failure_threshold == 3

    def test_get_circuit_breaker_returns_existing(self):
        """Test get_circuit_breaker returns existing instance."""
        config1 = CircuitBreakerConfig(name="existing_cb", failure_threshold=3)
        cb1 = get_circuit_breaker("existing_cb", config1)

        config2 = CircuitBreakerConfig(name="existing_cb", failure_threshold=5)
        cb2 = get_circuit_breaker("existing_cb", config2)

        # Should return the same instance
        assert cb1 is cb2
        # Should keep original config
        assert cb1.config.failure_threshold == 3

    def test_reset_circuit_breaker(self):
        """Test reset_circuit_breaker function."""
        config = CircuitBreakerConfig(name="reset_test", failure_threshold=1)
        cb = get_circuit_breaker("reset_test", config)

        async def failing_function():
            raise ValueError("Test error")

        async def test_reset():
            # Cause failure to open circuit
            with pytest.raises(ValueError):
                await cb.call(failing_function)

            assert cb.is_open

            # Reset via global function
            reset_circuit_breaker("reset_test")

            assert cb.is_closed
            assert cb.failure_count == 0

        asyncio.run(test_reset())

    def test_get_circuit_breaker_state(self):
        """Test get_circuit_breaker_state function."""
        config = CircuitBreakerConfig(name="state_test")
        cb = get_circuit_breaker("state_test", config)

        # Initially closed
        assert get_circuit_breaker_state("state_test") == "closed"

        async def failing_function():
            raise ValueError("Test error")

        async def test_state():
            # Cause failures to open circuit
            for i in range(cb.config.failure_threshold):
                with pytest.raises(ValueError):
                    await cb.call(failing_function)

            assert get_circuit_breaker_state("state_test") == "open"

        asyncio.run(test_state())

    def test_nonexistent_circuit_breaker_state(self):
        """Test get_circuit_breaker_state with nonexistent circuit breaker."""
        assert get_circuit_breaker_state("nonexistent") is None


class TestCircuitBreakerErrorHandling:
    """Test circuit breaker error handling."""

    def test_exception_in_call_records_failure(self):
        """Test that exceptions in function calls are recorded as failures."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)

        async def exception_function():
            raise RuntimeError("Test runtime error")

        async def test_exception():
            with pytest.raises(RuntimeError):
                await cb.call(exception_function)

            assert cb.failure_count == 1
            assert cb.is_closed  # Should still be closed after 1 failure

        asyncio.run(test_exception())

    def test_keyboard_interrupt_passthrough(self):
        """Test that KeyboardInterrupt passes through without affecting circuit breaker."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)

        async def interrupt_function():
            raise KeyboardInterrupt("Test interrupt")

        async def test_interrupt():
            with pytest.raises(KeyboardInterrupt):
                await cb.call(interrupt_function)

            # Circuit breaker should not record KeyboardInterrupt as a failure
            assert cb.failure_count == 0
            assert cb.is_closed

        asyncio.run(test_interrupt())

    def test_system_exit_passthrough(self):
        """Test that SystemExit passes through without affecting circuit breaker."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)

        async def exit_function():
            raise SystemExit("Test exit")

        async def test_exit():
            with pytest.raises(SystemExit):
                await cb.call(exit_function)

            # Circuit breaker should not record SystemExit as a failure
            assert cb.failure_count == 0
            assert cb.is_closed

        asyncio.run(test_exit())


class TestCircuitBreakerConcurrency:
    """Test circuit breaker concurrent access patterns."""

    def test_concurrent_calls_same_circuit_breaker(self):
        """Test multiple concurrent calls to the same circuit breaker."""
        config = CircuitBreakerConfig(
            name="concurrent_test",
            failure_threshold=10,  # High threshold to avoid opening
            recovery_timeout=0.1
        )
        cb = get_circuit_breaker("concurrent_test", config)

        async def successful_function():
            await asyncio.sleep(0.01)  # Small delay to simulate work
            return "success"

        async def test_concurrent_calls():
            # Make multiple concurrent calls
            tasks = [cb.call(successful_function) for _ in range(20)]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert len(results) == 20
            assert all(result == "success" for result in results)

            # Circuit breaker should remain closed
            assert cb.is_closed
            assert cb.failure_count == 0

        asyncio.run(test_concurrent_calls())

    def test_concurrent_calls_with_failures(self):
        """Test concurrent calls when some fail."""
        config = CircuitBreakerConfig(
            name="concurrent_failure_test",
            failure_threshold=5,
            recovery_timeout=0.1
        )
        cb = get_circuit_breaker("concurrent_failure_test", config)

        call_count = 0

        async def sometimes_failing_function():
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:  # Fail every 3rd call
                raise ValueError(f"Failure #{call_count}")
            await asyncio.sleep(0.01)
            return f"success_{call_count}"

        async def test_concurrent_failures():
            nonlocal call_count
            call_count = 0

            # Make concurrent calls where some will fail
            tasks = [cb.call(sometimes_failing_function) for _ in range(15)]
            results = []

            for task in tasks:
                try:
                    result = await task
                    results.append(result)
                except ValueError:
                    pass  # Expected failures

            # Should have some successes and some failures
            assert len(results) > 0
            assert call_count == 15

            # Circuit breaker should handle concurrent failures correctly
            assert cb.failure_count > 0
            assert cb.failure_count <= 5  # Should not exceed threshold due to concurrency

        asyncio.run(test_concurrent_failures())

    def test_concurrent_state_transitions(self):
        """Test concurrent access during state transitions."""
        config = CircuitBreakerConfig(
            name="state_transition_test",
            failure_threshold=3,
            recovery_timeout=0.05,
            success_threshold=2
        )
        cb = get_circuit_breaker("state_transition_test", config)

        async def failing_function():
            raise ValueError("Test error")

        async def successful_function():
            return "success"

        async def test_state_transitions():
            # First, cause failures to open the circuit
            for i in range(3):
                try:
                    await cb.call(failing_function)
                except ValueError:
                    pass

            assert cb.is_open

            # Wait for recovery timeout
            await asyncio.sleep(0.1)

            # Make concurrent calls that should transition to half-open
            tasks = [cb.call(successful_function) for _ in range(5)]
            results = await asyncio.gather(*tasks)

            # All calls should succeed
            assert len(results) == 5
            assert all(result == "success" for result in results)

            # Circuit breaker should eventually transition to closed
            # (may still be half-open depending on timing)
            assert not cb.is_open

        asyncio.run(test_state_transitions())


class TestCircuitBreakerLongRunning:
    """Test circuit breaker behavior over extended periods."""

    def test_long_running_successful_operation(self):
        """Test circuit breaker during long periods of successful operation."""
        config = CircuitBreakerConfig(
            name="long_running_success_test",
            failure_threshold=5,
            recovery_timeout=0.1
        )
        cb = get_circuit_breaker("long_running_success_test", config)

        async def successful_function(delay=0.01):
            await asyncio.sleep(delay)
            return "success"

        async def test_long_running():
            # Simulate long-running operation with many successful calls
            for i in range(50):
                result = await cb.call(successful_function, 0.001)
                assert result == "success"

                # Circuit should remain closed and healthy
                assert cb.is_closed
                assert cb.failure_count == 0

                # Small delay to simulate real operation
                await asyncio.sleep(0.001)

        asyncio.run(test_long_running())

    def test_recovery_after_prolonged_failure(self):
        """Test recovery after extended period of failures."""
        config = CircuitBreakerConfig(
            name="prolonged_failure_test",
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = get_circuit_breaker("prolonged_failure_test", config)

        async def failing_function():
            raise ValueError("Prolonged failure")

        async def successful_function():
            return "recovery_success"

        async def test_prolonged_failure():
            # Cause initial failures to open circuit
            for i in range(2):
                try:
                    await cb.call(failing_function)
                except ValueError:
                    pass

            assert cb.is_open

            # Wait for recovery timeout
            await asyncio.sleep(0.15)

            # Make successful calls to test recovery
            for i in range(3):
                result = await cb.call(successful_function)
                assert result == "recovery_success"

                # Small delay between calls
                await asyncio.sleep(0.01)

            # Should eventually recover to closed state
            assert cb.is_closed

        asyncio.run(test_prolonged_failure())


class TestCircuitBreakerMemoryManagement:
    """Test circuit breaker memory management and cleanup."""

    def test_remove_circuit_breaker(self):
        """Test removing circuit breakers from global registry."""
        config = CircuitBreakerConfig(name="memory_test")
        cb = get_circuit_breaker("memory_test", config)

        # Verify circuit breaker exists
        assert get_circuit_breaker_state("memory_test") == "closed"

        # Remove from registry
        remove_circuit_breaker("memory_test")

        # Verify it's gone
        assert get_circuit_breaker_state("memory_test") is None

        # Creating new circuit breaker with same name should work
        cb2 = get_circuit_breaker("memory_test", config)
        assert cb2 is not cb  # Should be different instance

    def test_cleanup_circuit_breakers(self):
        """Test circuit breaker cleanup function."""
        # Create multiple circuit breakers
        configs = [
            CircuitBreakerConfig(name=f"cleanup_test_{i}")
            for i in range(3)
        ]

        for config in configs:
            get_circuit_breaker(config.name, config)

        # Verify they exist
        for config in configs:
            assert get_circuit_breaker_state(config.name) == "closed"

        # Run cleanup (currently just returns count)
        removed_count = cleanup_circuit_breakers()
        assert isinstance(removed_count, int)
        assert removed_count >= 0

        # Circuit breakers should still exist after cleanup
        # (cleanup function doesn't actually remove any by default)
        for config in configs:
            assert get_circuit_breaker_state(config.name) == "closed"