"""Retry handler with exponential backoff.

Provides robust error recovery for API calls and network operations.
"""

import asyncio
import time
from typing import Callable, Any, TypeVar, Optional, Tuple, List
from functools import wraps
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryHandler:
    """Handles retries with exponential backoff and jitter."""

    def __init__(
        self,
        max_attempts: int = 4,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        """Initialize retry handler.

        Args:
            max_attempts: Maximum retry attempts
            base_delay: Initial delay in seconds
            max_delay: Maximum delay between retries
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to prevent thundering herd
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

        self.stats = {
            "total_calls": 0,
            "total_retries": 0,
            "total_failures": 0,
            "retry_by_exception": {},
        }

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt with exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )

        if self.jitter:
            import random
            # Add jitter: ±25% randomization
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)

        return max(delay, 0)

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        retry_exceptions: Optional[Tuple[type, ...]] = None,
        on_retry: Optional[Callable[[Exception, int], None]] = None,
        **kwargs
    ) -> Any:
        """Execute function with retry logic.

        Args:
            func: Function to execute (can be sync or async)
            *args: Positional arguments for func
            retry_exceptions: Tuple of exception types to retry on
            on_retry: Callback function called on each retry
            **kwargs: Keyword arguments for func

        Returns:
            Function result

        Raises:
            Exception: Last exception if all retries exhausted
        """
        if retry_exceptions is None:
            retry_exceptions = (
                ConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
                OSError,
            )

        self.stats["total_calls"] += 1
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                # Execute function (handle both sync and async)
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success - log if this was a retry
                if attempt > 0:
                    logger.info(
                        f"[RetryHandler] Success after {attempt} retries: {func.__name__}"
                    )

                return result

            except retry_exceptions as e:
                last_exception = e
                exception_type = type(e).__name__

                # Update stats
                self.stats["total_retries"] += 1
                if exception_type not in self.stats["retry_by_exception"]:
                    self.stats["retry_by_exception"][exception_type] = 0
                self.stats["retry_by_exception"][exception_type] += 1

                # Check if we should retry
                if attempt < self.max_attempts - 1:
                    delay = self.calculate_delay(attempt)
                    logger.warning(
                        f"[RetryHandler] Attempt {attempt + 1}/{self.max_attempts} failed "
                        f"for {func.__name__}: {e}. Retrying in {delay:.2f}s..."
                    )

                    # Call retry callback if provided
                    if on_retry:
                        try:
                            on_retry(e, attempt)
                        except Exception as callback_error:
                            logger.warning(
                                f"[RetryHandler] Retry callback error: {callback_error}"
                            )

                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[RetryHandler] All {self.max_attempts} attempts failed "
                        f"for {func.__name__}: {e}"
                    )
                    self.stats["total_failures"] += 1

            except Exception as e:
                # Non-retryable exception - fail immediately
                logger.error(
                    f"[RetryHandler] Non-retryable exception in {func.__name__}: {e}"
                )
                self.stats["total_failures"] += 1
                raise

        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(f"Retry exhausted for {func.__name__}")

    def get_stats(self) -> dict:
        """Get retry statistics.

        Returns:
            Statistics dictionary
        """
        return {
            **self.stats,
            "success_rate": (
                (self.stats["total_calls"] - self.stats["total_failures"])
                / self.stats["total_calls"] * 100
                if self.stats["total_calls"] > 0 else 0
            ),
            "avg_retries_per_call": (
                self.stats["total_retries"] / self.stats["total_calls"]
                if self.stats["total_calls"] > 0 else 0
            ),
        }


def retry_async(
    max_attempts: int = 4,
    base_delay: float = 2.0,
    retry_exceptions: Optional[Tuple[type, ...]] = None,
    exponential_base: float = 2.0,
):
    """Decorator for async functions with retry logic.

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay in seconds
        retry_exceptions: Tuple of exception types to retry on
        exponential_base: Base for exponential backoff

    Returns:
        Decorated function

    Example:
        @retry_async(max_attempts=3, base_delay=1.0)
        async def fetch_data():
            # ... network call ...
            pass
    """
    if retry_exceptions is None:
        retry_exceptions = (
            ConnectionError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
        )

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            handler = RetryHandler(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
            )
            return await handler.execute_with_retry(
                func,
                *args,
                retry_exceptions=retry_exceptions,
                **kwargs
            )
        return wrapper
    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for failing services.

    Prevents cascading failures by temporarily blocking calls to failing services.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type to count as failure
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            Exception: Circuit open or function error
        """
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
                logger.info("[CircuitBreaker] Attempting recovery (HALF_OPEN)")
            else:
                raise Exception(
                    f"Circuit breaker OPEN. Service unavailable. "
                    f"Retry after {self.recovery_timeout}s"
                )

        try:
            # Execute function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Success - reset on half-open
            if self.state == "HALF_OPEN":
                self._reset()
                logger.info("[CircuitBreaker] Recovery successful (CLOSED)")

            return result

        except self.expected_exception as e:
            self._record_failure()
            raise

    def _record_failure(self) -> None:
        """Record a failure and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"[CircuitBreaker] Circuit OPEN after {self.failure_count} failures"
            )

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return True
        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    def _reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"

    def get_state(self) -> dict:
        """Get circuit breaker state.

        Returns:
            State dictionary
        """
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
        }
