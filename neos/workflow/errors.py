"""Structured error handling for workflow system

Provides categorized errors with metadata for better debugging,
recovery strategies, and error analytics.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


class ErrorCategory(Enum):
    """Error categories for workflow failures

    Each category has different retry strategies and handling logic:
    - AGENT_TIMEOUT: Retryable with exponential backoff
    - AGENT_FAILURE: Retryable, may use fallback agents
    - LLM_ERROR: Retryable with rate limit handling
    - DATABASE_ERROR: Retryable with fixed backoff
    - VALIDATION_ERROR: Non-retryable, requires user intervention
    - EXTERNAL_API_ERROR: Retryable with circuit breaker
    - CONFIGURATION_ERROR: Non-retryable, system misconfiguration
    - NETWORK_ERROR: Retryable with exponential backoff
    """
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_FAILURE = "agent_failure"
    LLM_ERROR = "llm_error"
    DATABASE_ERROR = "database_error"
    VALIDATION_ERROR = "validation_error"
    EXTERNAL_API_ERROR = "external_api_error"
    CONFIGURATION_ERROR = "configuration_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class WorkflowError:
    """Structured error with metadata for workflow failures

    Attributes:
        category: Error category (determines retry strategy)
        message: Human-readable error message
        node: Workflow node where error occurred
        timestamp: ISO 8601 timestamp
        recoverable: Whether error can be recovered via retry
        context: Additional error context (stack trace, request details, etc.)
        retry_count: Number of retries attempted
        error_code: Optional error code for categorization
    """
    category: ErrorCategory
    message: str
    node: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    recoverable: bool = True
    context: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization"""
        return {
            "category": self.category.value,
            "message": self.message,
            "node": self.node,
            "timestamp": self.timestamp,
            "recoverable": self.recoverable,
            "context": self.context,
            "retry_count": self.retry_count,
            "error_code": self.error_code
        }

    def __str__(self) -> str:
        """String representation for logging"""
        return (
            f"[{self.category.value}] {self.message} "
            f"(node={self.node}, retries={self.retry_count}, "
            f"recoverable={self.recoverable})"
        )


class ErrorRecoveryStrategy(Enum):
    """Recovery strategies for different error categories

    Defines how the system should respond to different error types:
    - RETRY_EXPONENTIAL: Retry with exponential backoff (1s, 2s, 4s, ...)
    - RETRY_FIXED: Retry with fixed delay (e.g., 1s every time)
    - RETRY_IMMEDIATE: Retry immediately without delay
    - FALLBACK: Try alternative approach/agent
    - SKIP: Skip failed step and continue workflow
    - ABORT: Abort entire workflow
    - USER_INTERVENTION: Requires user action
    """
    RETRY_EXPONENTIAL = "retry_exponential"
    RETRY_FIXED = "retry_fixed"
    RETRY_IMMEDIATE = "retry_immediate"
    FALLBACK = "fallback"
    SKIP = "skip"
    ABORT = "abort"
    USER_INTERVENTION = "user_intervention"


# TODO: Implement error recovery strategy mapping
# This is a design decision that affects system reliability and user experience.
#
# Trade-offs to consider:
# 1. Aggressive retries (more retries) vs. Fast failure (fewer retries)
#    - Aggressive: Better success rate but higher latency and cost
#    - Fast failure: Lower latency but may give up on recoverable errors
#
# 2. Exponential backoff vs. Fixed delay
#    - Exponential: Better for rate limits and system recovery
#    - Fixed: More predictable latency
#
# 3. Fallback strategies
#    - When should we try alternative agents vs. just retry?
#    - How to prioritize fallback options?
#
# 4. User experience
#    - Should validation errors immediately abort or provide suggestions?
#    - When to show partial results vs. complete failure?
#
# Your task: Implement get_recovery_strategy() function below
# Consider the trade-offs above and the system's use cases.

def get_recovery_strategy(error_category: ErrorCategory) -> ErrorRecoveryStrategy:
    """Determine recovery strategy for an error category

    Args:
        error_category: The category of error

    Returns:
        ErrorRecoveryStrategy: The recommended recovery strategy

    Implementation Philosophy:
    - Transient errors (timeouts, network, LLM rate limits) → RETRY_EXPONENTIAL
    - System errors (database) → RETRY_FIXED (predictable recovery)
    - Permanent errors (validation, config) → ABORT (no point retrying)
    - Agent failures → FALLBACK (try alternative agents)
    - External APIs → RETRY_EXPONENTIAL (respect rate limits)
    """
    strategy_map = {
        # Transient errors - retry with exponential backoff (respects rate limits)
        ErrorCategory.AGENT_TIMEOUT: ErrorRecoveryStrategy.RETRY_EXPONENTIAL,
        ErrorCategory.LLM_ERROR: ErrorRecoveryStrategy.RETRY_EXPONENTIAL,
        ErrorCategory.NETWORK_ERROR: ErrorRecoveryStrategy.RETRY_EXPONENTIAL,
        ErrorCategory.EXTERNAL_API_ERROR: ErrorRecoveryStrategy.RETRY_EXPONENTIAL,

        # System errors - retry with fixed delay (predictable recovery)
        ErrorCategory.DATABASE_ERROR: ErrorRecoveryStrategy.RETRY_FIXED,

        # Agent failures - try fallback agents first, then retry
        ErrorCategory.AGENT_FAILURE: ErrorRecoveryStrategy.FALLBACK,

        # Permanent errors - abort immediately (no recovery possible)
        ErrorCategory.VALIDATION_ERROR: ErrorRecoveryStrategy.ABORT,
        ErrorCategory.CONFIGURATION_ERROR: ErrorRecoveryStrategy.ABORT,

        # Unknown errors - be conservative, skip and continue
        ErrorCategory.UNKNOWN_ERROR: ErrorRecoveryStrategy.SKIP,
    }

    return strategy_map.get(error_category, ErrorRecoveryStrategy.ABORT)


def get_max_retries(error_category: ErrorCategory) -> int:
    """Get maximum retry count for an error category

    Args:
        error_category: The category of error

    Returns:
        int: Maximum number of retries allowed

    Implementation Philosophy:
    - High-cost errors (LLM) → Few retries (2-3) to control costs
    - Network/timeout errors → More retries (5) for resilience
    - Database errors → Moderate retries (3) with fixed backoff
    - Permanent errors → 0 retries (impossible to recover)
    - Unknown errors → Conservative (1 retry) to avoid loops
    """
    retry_limits = {
        # Transient errors - more retries for resilience
        ErrorCategory.AGENT_TIMEOUT: 5,  # Timeouts are often transient
        ErrorCategory.NETWORK_ERROR: 5,  # Network issues usually resolve quickly
        ErrorCategory.EXTERNAL_API_ERROR: 3,  # APIs may have rate limits

        # Expensive errors - fewer retries to control costs
        ErrorCategory.LLM_ERROR: 2,  # LLM calls are expensive (tokens + latency)

        # System errors - moderate retries
        ErrorCategory.DATABASE_ERROR: 3,  # DB usually recovers quickly
        ErrorCategory.AGENT_FAILURE: 2,  # Try fallback, then give up

        # Permanent errors - no retries
        ErrorCategory.VALIDATION_ERROR: 0,  # User input error, can't auto-fix
        ErrorCategory.CONFIGURATION_ERROR: 0,  # System misconfiguration

        # Unknown errors - conservative single retry
        ErrorCategory.UNKNOWN_ERROR: 1,  # Avoid infinite loops
    }

    return retry_limits.get(error_category, 0)  # Default: don't retry unknown categories


def categorize_exception(exception: Exception, node: str = "unknown") -> WorkflowError:
    """Convert a Python exception to a WorkflowError

    Args:
        exception: The exception to categorize
        node: The workflow node where exception occurred

    Returns:
        WorkflowError: Structured error object
    """
    import asyncio

    # Categorize based on exception type
    if isinstance(exception, asyncio.TimeoutError):
        category = ErrorCategory.AGENT_TIMEOUT
        recoverable = True
    elif isinstance(exception, ConnectionError):
        category = ErrorCategory.NETWORK_ERROR
        recoverable = True
    elif isinstance(exception, ValueError):
        category = ErrorCategory.VALIDATION_ERROR
        recoverable = False
    elif "psycopg" in str(type(exception).__module__):
        category = ErrorCategory.DATABASE_ERROR
        recoverable = True
    elif "openai" in str(type(exception).__module__) or "anthropic" in str(type(exception).__module__):
        category = ErrorCategory.LLM_ERROR
        recoverable = True
    else:
        category = ErrorCategory.UNKNOWN_ERROR
        recoverable = True

    return WorkflowError(
        category=category,
        message=str(exception),
        node=node,
        recoverable=recoverable,
        context={
            "exception_type": type(exception).__name__,
            "exception_module": type(exception).__module__,
        }
    )
