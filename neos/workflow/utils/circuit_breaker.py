"""Circuit Breaker pattern for external API protection

Prevents cascading failures by "opening" the circuit when an API fails repeatedly.
Implements the classic three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Circuit is open, requests fail fast without calling the API
- HALF_OPEN: Testing if the service recovered, limited requests allowed
"""

import time
import asyncio
import logging
from enum import Enum
from typing import Callable, TypeVar, Any, Optional
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit tripped, fast-fail mode
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit is open and request is rejected"""
    pass


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior

    Attributes:
        failure_threshold: Number of failures before opening circuit (default: 5)
        success_threshold: Number of successes in HALF_OPEN to close circuit (default: 2)
        timeout_seconds: Time to wait before trying HALF_OPEN (default: 60)
        half_open_max_calls: Max concurrent calls in HALF_OPEN state (default: 1)
        expected_exception: Exception type to consider as failure (default: Exception)
        excluded_exceptions: Tuple of exception types to NOT count as failures.
            These exceptions will still propagate but won't trigger the circuit breaker.
            Useful for separating "slow API" (TimeoutError) from "dead API" (ConnectionError).
    """
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60.0
    half_open_max_calls: int = 1
    expected_exception: type = Exception
    excluded_exceptions: tuple = ()


@dataclass
class CircuitBreakerStats:
    """Statistics for monitoring circuit breaker health"""
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    total_rejections: int = 0  # Rejected due to open circuit
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    def failure_rate(self) -> float:
        """Calculate failure rate (0.0 to 1.0)"""
        if self.total_calls == 0:
            return 0.0
        return self.total_failures / self.total_calls

    def rejection_rate(self) -> float:
        """Calculate rejection rate (0.0 to 1.0)"""
        total_attempts = self.total_calls + self.total_rejections
        if total_attempts == 0:
            return 0.0
        return self.total_rejections / total_attempts


class CircuitBreaker:
    """Circuit breaker for external API calls

    Protects against cascading failures by failing fast when an external
    service is down or degraded.

    Example:
        ```python
        # Create circuit breaker for Tavily API
        tavily_breaker = CircuitBreaker(
            name="tavily_api",
            failure_threshold=3,  # Open after 3 failures
            timeout_seconds=30  # Wait 30s before retry
        )

        # Use circuit breaker
        @tavily_breaker.call
        async def search_tavily(query: str):
            return await tavily_client.search(query)

        try:
            result = await search_tavily("test")
        except CircuitBreakerError:
            # Circuit is open, use fallback
            result = await fallback_search("test")
        ```
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        self._half_open_calls = 0

        logger.info(
            f"[CircuitBreaker] {self.name} initialized: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"timeout={self.config.timeout_seconds}s"
        )

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of func

        Raises:
            CircuitBreakerError: If circuit is open
            Original exception: If func fails
        """
        # Check if we can make the call
        async with self._lock:
            if not await self._can_execute():
                self.stats.total_rejections += 1
                logger.warning(
                    f"[CircuitBreaker] {self.name} is {self.state.value}, "
                    f"rejecting call (rejections={self.stats.total_rejections})"
                )
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is {self.state.value}"
                )

            if self.state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result

        except self.config.expected_exception as e:
            # excluded_exceptions에 해당하면 CB 실패로 카운트하지 않고 전파만 한다.
            # "느린 API" (TimeoutError)와 "죽은 API" (ConnectionError)를 구분하기 위함.
            if self.config.excluded_exceptions and isinstance(e, self.config.excluded_exceptions):
                logger.info(
                    f"[CircuitBreaker] {self.name} excluded exception (not counted as failure): "
                    f"{type(e).__name__}: {e}"
                )
                raise

            await self._on_failure(e)
            raise

        finally:
            if self.state == CircuitState.HALF_OPEN:
                async with self._lock:
                    self._half_open_calls -= 1

    async def _can_execute(self) -> bool:
        """Check if we can execute a call in current state"""
        if self.state == CircuitState.CLOSED:
            return True

        elif self.state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if self.stats.last_failure_time:
                time_since_failure = time.time() - self.stats.last_failure_time
                if time_since_failure >= self.config.timeout_seconds:
                    # Transition to HALF_OPEN
                    self._transition_to(CircuitState.HALF_OPEN)
                    logger.info(
                        f"[CircuitBreaker] {self.name} transitioning to HALF_OPEN "
                        f"after {time_since_failure:.1f}s"
                    )
                    return True
            return False

        elif self.state == CircuitState.HALF_OPEN:
            # Allow limited concurrent calls
            return self._half_open_calls < self.config.half_open_max_calls

        return False

    async def _on_success(self):
        """Handle successful call"""
        async with self._lock:
            self.stats.total_calls += 1
            self.stats.total_successes += 1
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0
            self.stats.last_success_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # Check if we should close the circuit
                if self.stats.consecutive_successes >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    logger.info(
                        f"[CircuitBreaker] {self.name} recovered, closing circuit "
                        f"(successes={self.stats.consecutive_successes})"
                    )

    async def _on_failure(self, exception: Exception):
        """Handle failed call"""
        async with self._lock:
            self.stats.total_calls += 1
            self.stats.total_failures += 1
            self.stats.consecutive_failures += 1
            self.stats.consecutive_successes = 0
            self.stats.last_failure_time = time.time()

            if self.state == CircuitState.CLOSED:
                # Check if we should open the circuit
                if self.stats.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    logger.error(
                        f"[CircuitBreaker] {self.name} opening circuit "
                        f"(failures={self.stats.consecutive_failures}). Error: {exception}"
                    )

            elif self.state == CircuitState.HALF_OPEN:
                # Failed in HALF_OPEN, go back to OPEN
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"[CircuitBreaker] {self.name} failed in HALF_OPEN, "
                    f"reopening circuit. Error: {exception}"
                )

    def _transition_to(self, new_state: CircuitState):
        """Transition to a new state"""
        old_state = self.state
        self.state = new_state

        if new_state == CircuitState.CLOSED:
            self.stats.consecutive_failures = 0
            self.stats.consecutive_successes = 0

        logger.info(
            f"[CircuitBreaker] {self.name} state transition: "
            f"{old_state.value} → {new_state.value}"
        )

    def get_stats(self) -> dict:
        """Get circuit breaker statistics for monitoring"""
        return {
            "name": self.name,
            "state": self.state.value,
            "total_calls": self.stats.total_calls,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "total_rejections": self.stats.total_rejections,
            "failure_rate": self.stats.failure_rate(),
            "rejection_rate": self.stats.rejection_rate(),
            "consecutive_failures": self.stats.consecutive_failures,
            "consecutive_successes": self.stats.consecutive_successes,
        }

    def reset(self):
        """Reset circuit breaker to initial state (for testing)"""
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._half_open_calls = 0
        logger.info(f"[CircuitBreaker] {self.name} reset to CLOSED state")


# Global circuit breakers for common external APIs
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreaker:
    """Get or create a circuit breaker by name

    Maintains singleton circuit breakers per name for consistent behavior
    across the application.

    Args:
        name: Circuit breaker name (e.g., "tavily_api", "mcp_server")
        config: Optional configuration (used only when creating new breaker)

    Returns:
        CircuitBreaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, config)

    return _circuit_breakers[name]


def with_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None):
    """Decorator to protect function with circuit breaker

    Args:
        name: Circuit breaker name
        config: Optional configuration

    Example:
        ```python
        @with_circuit_breaker("tavily_api", CircuitBreakerConfig(failure_threshold=3))
        async def search_tavily(query: str):
            return await tavily_client.search(query)
        ```
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        breaker = get_circuit_breaker(name, config)

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)

        return wrapper
    return decorator
