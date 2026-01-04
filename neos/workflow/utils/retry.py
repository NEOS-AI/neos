"""Intelligent retry mechanism with category-specific strategies

Implements retry logic based on ErrorCategory, using the recovery strategies
and retry limits defined in neos/workflow/errors.py.
"""

import asyncio
import time
import logging
from typing import Callable, TypeVar, Any, Optional
from functools import wraps

from neos.workflow.errors import (
    ErrorCategory,
    WorkflowError,
    ErrorRecoveryStrategy,
    get_recovery_strategy,
    get_max_retries,
    categorize_exception,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


def calculate_backoff_delay(
    retry_count: int,
    strategy: ErrorRecoveryStrategy,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> float:
    """Calculate backoff delay based on retry strategy

    Args:
        retry_count: Current retry attempt (0-indexed)
        strategy: Recovery strategy (determines backoff algorithm)
        base_delay: Base delay in seconds (default: 1.0)
        max_delay: Maximum delay in seconds (default: 60.0)

    Returns:
        float: Delay in seconds before next retry
    """
    if strategy == ErrorRecoveryStrategy.RETRY_IMMEDIATE:
        return 0.0

    elif strategy == ErrorRecoveryStrategy.RETRY_FIXED:
        return base_delay

    elif strategy == ErrorRecoveryStrategy.RETRY_EXPONENTIAL:
        # Exponential backoff: 1s, 2s, 4s, 8s, 16s, ... (capped at max_delay)
        delay = base_delay * (2 ** retry_count)
        return min(delay, max_delay)

    else:
        # Unknown strategy, use fixed delay
        return base_delay


async def retry_with_strategy(
    func: Callable[..., T],
    *args,
    error_category: ErrorCategory,
    node: str = "unknown",
    context: Optional[dict] = None,
    **kwargs
) -> T:
    """Execute function with intelligent retry based on error category

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        error_category: Expected error category for this operation
        node: Workflow node name (for error tracking)
        context: Additional context for error logging
        **kwargs: Keyword arguments for func

    Returns:
        Result of func execution

    Raises:
        WorkflowError: If all retries exhausted or non-retryable error

    Example:
        ```python
        result = await retry_with_strategy(
            tavily_search,
            query="test",
            error_category=ErrorCategory.EXTERNAL_API_ERROR,
            node="search_orchestrator"
        )
        ```
    """
    strategy = get_recovery_strategy(error_category)
    max_retries = get_max_retries(error_category)

    last_error: Optional[WorkflowError] = None

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            logger.debug(
                f"[Retry] Executing {func.__name__} (attempt {attempt + 1}/{max_retries + 1})"
            )
            result = await func(*args, **kwargs)

            # Success!
            if attempt > 0:
                logger.info(
                    f"[Retry] {func.__name__} succeeded after {attempt} retries "
                    f"(category={error_category.value}, strategy={strategy.value})"
                )
            return result

        except Exception as e:
            # Categorize the error
            workflow_error = categorize_exception(e, node=node)
            workflow_error.retry_count = attempt
            if context:
                workflow_error.context.update(context)

            last_error = workflow_error

            # Check if we should retry
            if attempt >= max_retries:
                logger.error(
                    f"[Retry] {func.__name__} failed after {max_retries} retries: "
                    f"{workflow_error}"
                )
                raise workflow_error

            # Check if error is non-recoverable
            if not workflow_error.recoverable:
                logger.error(
                    f"[Retry] {func.__name__} failed with non-recoverable error: "
                    f"{workflow_error}"
                )
                raise workflow_error

            # Calculate backoff delay
            delay = calculate_backoff_delay(attempt, strategy)

            logger.warning(
                f"[Retry] {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {delay:.1f}s... Error: {workflow_error.message}"
            )

            if delay > 0:
                await asyncio.sleep(delay)

    # Should never reach here, but just in case
    if last_error:
        raise last_error
    else:
        raise RuntimeError(f"Retry logic failed for {func.__name__}")


def with_retry(error_category: ErrorCategory, node: str = "unknown"):
    """Decorator for automatic retry with error category

    Args:
        error_category: Expected error category for this function
        node: Workflow node name (for error tracking)

    Example:
        ```python
        @with_retry(error_category=ErrorCategory.EXTERNAL_API_ERROR, node="tavily_search")
        async def search_tavily(query: str) -> List[SearchResult]:
            # ... implementation
            pass
        ```
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_with_strategy(
                func,
                *args,
                error_category=error_category,
                node=node,
                **kwargs
            )
        return wrapper
    return decorator


class RetryContext:
    """Context manager for retry operations with statistics tracking

    Tracks retry statistics for monitoring and debugging.

    Example:
        ```python
        async with RetryContext(
            error_category=ErrorCategory.LLM_ERROR,
            node="response_generator"
        ) as retry_ctx:
            result = await llm.ainvoke(prompt)
            retry_ctx.set_result(result)

        print(f"Total attempts: {retry_ctx.total_attempts}")
        print(f"Total delay: {retry_ctx.total_delay_seconds}s")
        ```
    """

    def __init__(
        self,
        error_category: ErrorCategory,
        node: str = "unknown",
        context: Optional[dict] = None
    ):
        self.error_category = error_category
        self.node = node
        self.context = context or {}

        self.total_attempts = 0
        self.total_delay_seconds = 0.0
        self.errors: list[WorkflowError] = []
        self.result: Any = None
        self.success = False

    async def __aenter__(self):
        self.total_attempts = 0
        self.errors = []
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            # Exception occurred
            self.success = False
            workflow_error = categorize_exception(exc_val, node=self.node)
            self.errors.append(workflow_error)
            logger.error(
                f"[RetryContext] Operation failed in {self.node}: {workflow_error}"
            )
        else:
            self.success = True

        # Log statistics
        if self.total_attempts > 1:
            logger.info(
                f"[RetryContext] {self.node} completed: "
                f"attempts={self.total_attempts}, "
                f"total_delay={self.total_delay_seconds:.1f}s, "
                f"success={self.success}"
            )

        return False  # Don't suppress exceptions

    def set_result(self, result: Any):
        """Set the successful result"""
        self.result = result
        self.success = True
