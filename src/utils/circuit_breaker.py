"""Circuit breaker pattern implementation for external service protection.

This module provides a simple, robust circuit breaker that prevents cascade failures
during external service outages by failing fast when services are unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5
    recovery_timeout: float = 300.0  # 5 minutes for unattended operation
    success_threshold: int = 3
    name: str = "default"


class CircuitBreakerOpenException(Exception):
    """Exception raised when circuit breaker is in OPEN state."""

    pass


class CircuitBreaker:
    """Simple circuit breaker implementation with three states.

    CLOSED: Normal operation, requests pass through
    OPEN: Service is failing, requests fail fast
    HALF_OPEN: Testing if service has recovered
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        """Initialize circuit breaker with configuration.

        Args:
            config: Circuit breaker configuration
        """
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.last_used: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def call(
        self,
        func: Callable[[], T | Any],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result if successful

        Raises:
            CircuitBreakerOpenException: If circuit breaker is OPEN
            Exception: If function execution fails
        """
        self.last_used = time.monotonic()
        # Initial state check with lock
        async with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_recovery():
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    logging.info(
                        f"🔄 Circuit breaker '{self.config.name}' transitioning to HALF_OPEN"
                    )
                else:
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker '{self.config.name}' is OPEN"
                    )

        # Execute function without holding the lock to reduce contention
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)

            # Update state with lock
            async with self._lock:
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.config.success_threshold:
                        self._reset()
                        logging.info(
                            f"✅ Circuit breaker '{self.config.name}' recovered, transitioning to CLOSED"
                        )
                elif self.state == CircuitBreakerState.CLOSED:
                    # Reset failure count on successful call in CLOSED state
                    self.failure_count = 0

            return result

        except Exception:
            # Record failure with lock
            async with self._lock:
                self._record_failure()
            raise

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return True
        return (time.monotonic() - self.last_failure_time) >= self.config.recovery_timeout

    def _record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            logging.warning(
                f"🚨 Circuit breaker '{self.config.name}' opened after {self.failure_count} failures"
            )
        elif self.state == CircuitBreakerState.HALF_OPEN:
            # Go back to OPEN on any failure in HALF_OPEN
            self.state = CircuitBreakerState.OPEN
            logging.warning(
                f"⚠️ Circuit breaker '{self.config.name}' returned to OPEN after failure in HALF_OPEN"
            )

    def _reset(self) -> None:
        """Reset circuit breaker to initial state."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None

    @property
    def is_open(self) -> bool:
        """Check if circuit breaker is currently open."""
        return self.state == CircuitBreakerState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit breaker is currently closed."""
        return self.state == CircuitBreakerState.CLOSED

    @property
    def is_half_open(self) -> bool:
        """Check if circuit breaker is currently half-open."""
        return self.state == CircuitBreakerState.HALF_OPEN


# Global circuit breaker instances
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
    """Get or create a circuit breaker instance by name.

    Args:
        name: Circuit breaker name/identifier
        config: Optional configuration (uses defaults if not provided)

    Returns:
        Circuit breaker instance
    """
    if name not in _circuit_breakers:
        if config is None:
            config = CircuitBreakerConfig(name=name)
        _circuit_breakers[name] = CircuitBreaker(config)

    return _circuit_breakers[name]


def reset_circuit_breaker(name: str) -> None:
    """Reset a circuit breaker to initial state.

    Args:
        name: Circuit breaker name to reset
    """
    if name in _circuit_breakers:
        _circuit_breakers[name]._reset()
        logging.info(f"🔄 Circuit breaker '{name}' manually reset")


def get_circuit_breaker_state(name: str) -> str | None:
    """Get the current state of a circuit breaker.

    Args:
        name: Circuit breaker name

    Returns:
        Current state as string, or None if not found
    """
    if name in _circuit_breakers:
        return _circuit_breakers[name].state.value
    return None


def remove_circuit_breaker(name: str) -> None:
    """Remove a circuit breaker from the global registry.

    Args:
        name: Circuit breaker name to remove
    """
    if name in _circuit_breakers:
        del _circuit_breakers[name]
        logging.info(f"🗑️ Circuit breaker '{name}' removed from global registry")


def cleanup_circuit_breakers() -> int:
    """Clean up unused circuit breakers from the global registry.

    Removes circuit breakers that haven't been used for more than 1 hour.

    Returns:
        Number of circuit breakers removed
    """
    removed_count = 0
    current_time = time.monotonic()
    inactivity_timeout = 3600.0  # 1 hour

    for name, cb in list(_circuit_breakers.items()):
        if current_time - cb.last_used > inactivity_timeout:
            del _circuit_breakers[name]
            removed_count += 1
            logging.info(f"🗑️ Circuit breaker '{name}' cleaned up due to inactivity")

    return removed_count
