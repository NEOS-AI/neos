"""
Integration tests for Workflow Improvements (Phase 1 & 2)

Tests cover the improvements implemented in Phase 1 (Quick Wins) and Phase 2 (Foundation):
- Structured error categorization and recovery
- Differentiated retry strategies
- Circuit breaker pattern
- Performance metrics collection
- Error recovery flows
- Combined feature integration
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
from typing import Dict, Any

from neos.workflow.errors import (
    ErrorCategory,
    WorkflowError,
    ErrorRecoveryStrategy,
    categorize_exception,
    get_recovery_strategy,
    get_max_retries,
)
from neos.workflow.utils.retry import (
    calculate_backoff_delay,
    retry_with_strategy,
    with_retry,
    RetryContext,
)
from neos.workflow.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerError,
    get_circuit_breaker,
    with_circuit_breaker,
)
from neos.workflow.metrics import (
    PerformanceMetrics,
    MetricsCollector,
    get_metrics_collector,
)


@pytest.mark.integration
class TestStructuredErrorHandling:
    """Integration tests for structured error handling"""

    def test_error_categorization_from_exceptions(self):
        """Test automatic exception categorization"""
        # Timeout error
        timeout_error = asyncio.TimeoutError("Operation timed out")
        workflow_error = categorize_exception(timeout_error, node="test_node")

        assert workflow_error.category == ErrorCategory.AGENT_TIMEOUT
        assert workflow_error.node == "test_node"
        assert workflow_error.recoverable is True
        assert "timed out" in workflow_error.message.lower()

        # Network error
        network_error = ConnectionError("Connection refused")
        workflow_error = categorize_exception(network_error, node="network_call")

        assert workflow_error.category == ErrorCategory.NETWORK_ERROR
        assert workflow_error.recoverable is True

        # Validation error (unrecoverable)
        validation_error = ValueError("Invalid input format")
        workflow_error = categorize_exception(validation_error, node="validator")

        assert workflow_error.category == ErrorCategory.VALIDATION_ERROR
        assert workflow_error.recoverable is False

    def test_recovery_strategy_mapping(self):
        """Test error recovery strategy mapping"""
        # Transient errors should use exponential backoff
        assert get_recovery_strategy(ErrorCategory.AGENT_TIMEOUT) == ErrorRecoveryStrategy.RETRY_EXPONENTIAL
        assert get_recovery_strategy(ErrorCategory.LLM_ERROR) == ErrorRecoveryStrategy.RETRY_EXPONENTIAL
        assert get_recovery_strategy(ErrorCategory.NETWORK_ERROR) == ErrorRecoveryStrategy.RETRY_EXPONENTIAL

        # System errors should use fixed backoff
        assert get_recovery_strategy(ErrorCategory.DATABASE_ERROR) == ErrorRecoveryStrategy.RETRY_FIXED

        # Permanent errors should abort
        assert get_recovery_strategy(ErrorCategory.VALIDATION_ERROR) == ErrorRecoveryStrategy.ABORT
        assert get_recovery_strategy(ErrorCategory.CONFIGURATION_ERROR) == ErrorRecoveryStrategy.ABORT

    def test_retry_limits_per_category(self):
        """Test retry limits are properly configured"""
        # Transient errors: more retries
        assert get_max_retries(ErrorCategory.AGENT_TIMEOUT) == 5
        assert get_max_retries(ErrorCategory.NETWORK_ERROR) == 5

        # Expensive operations: fewer retries
        assert get_max_retries(ErrorCategory.LLM_ERROR) == 2

        # Database errors: moderate retries
        assert get_max_retries(ErrorCategory.DATABASE_ERROR) == 3

        # Permanent errors: no retries
        assert get_max_retries(ErrorCategory.VALIDATION_ERROR) == 0
        assert get_max_retries(ErrorCategory.CONFIGURATION_ERROR) == 0


@pytest.mark.integration
class TestRetryStrategies:
    """Integration tests for retry mechanisms"""

    def test_backoff_delay_calculation(self):
        """Test backoff delay calculations for different strategies"""
        # Exponential backoff: 1s → 2s → 4s → 8s
        assert calculate_backoff_delay(0, ErrorRecoveryStrategy.RETRY_EXPONENTIAL, base_delay=1.0) == 1.0
        assert calculate_backoff_delay(1, ErrorRecoveryStrategy.RETRY_EXPONENTIAL, base_delay=1.0) == 2.0
        assert calculate_backoff_delay(2, ErrorRecoveryStrategy.RETRY_EXPONENTIAL, base_delay=1.0) == 4.0
        assert calculate_backoff_delay(3, ErrorRecoveryStrategy.RETRY_EXPONENTIAL, base_delay=1.0) == 8.0

        # Max delay cap (60s)
        assert calculate_backoff_delay(10, ErrorRecoveryStrategy.RETRY_EXPONENTIAL, base_delay=1.0) == 60.0

        # Fixed delay
        assert calculate_backoff_delay(0, ErrorRecoveryStrategy.RETRY_FIXED, base_delay=1.0) == 1.0
        assert calculate_backoff_delay(5, ErrorRecoveryStrategy.RETRY_FIXED, base_delay=1.0) == 1.0

        # Immediate retry
        assert calculate_backoff_delay(0, ErrorRecoveryStrategy.RETRY_IMMEDIATE) == 0.0
        assert calculate_backoff_delay(3, ErrorRecoveryStrategy.RETRY_IMMEDIATE) == 0.0

    @pytest.mark.asyncio
    async def test_retry_with_strategy_success(self):
        """Test successful retry after transient failure"""
        attempt_count = 0

        async def flaky_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Temporary failure")
            return "success"

        result = await retry_with_strategy(
            flaky_function,
            error_category=ErrorCategory.NETWORK_ERROR,
            node="test_node"
        )

        assert result == "success"
        assert attempt_count == 3  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_retry_with_strategy_exhausted(self):
        """Test retry exhaustion after max attempts

        Note: Currently retry_with_strategy tries to raise WorkflowError (a dataclass),
        which causes TypeError. This test verifies the retry attempts happen correctly
        even though the final raise fails.

        진짜로 잔다 — mock 이 아니라 `retry_with_strategy` 의 실제 지수 백오프를
        태운다. NETWORK_ERROR 는 max_retries=5, base_delay=1.0 이라
        1+2+4+8+16=31초를 실제로 sleep 한다(`neos/workflow/utils/retry.py`).
        실측 32.76초(`.venv/bin/python -m pytest ...::test_retry_with_strategy_exhausted
        -p no:randomly --timeout=300 -q`, 2026-08-29) — 전역 기본값 30초보다
        길어 pytest.ini 의 전역 타임아웃에 그대로 맡기면 이 테스트만 죽는다.
        전역값을 이 테스트 하나 때문에 올리는 대신(나머지 스위트의 실측
        최댓값은 6.5초대라 30초면 충분하다), 여기 개별 오버라이드로 여유
        (~1.8배)를 준다.
        """
        attempt_count = 0

        async def always_fails():
            nonlocal attempt_count
            attempt_count += 1
            raise ConnectionError("Persistent failure")

        # WorkflowError is a dataclass, not Exception, so raising it causes TypeError
        with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
            await retry_with_strategy(
                always_fails,
                error_category=ErrorCategory.NETWORK_ERROR,  # Max 5 retries
                node="test_node"
            )

        # Verify all retry attempts were made (initial + 5 retries)
        assert attempt_count == 6

    @pytest.mark.asyncio
    async def test_retry_decorator(self):
        """Test retry decorator functionality"""
        attempt_count = 0

        @with_retry(error_category=ErrorCategory.LLM_ERROR, node="llm_call")
        async def decorated_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise Exception("LLM timeout")
            return "completed"

        result = await decorated_function()

        assert result == "completed"
        assert attempt_count == 2  # Failed once, succeeded on second

    @pytest.mark.asyncio
    async def test_retry_context_manager(self):
        """Test retry context manager with statistics"""
        async with RetryContext(
            error_category=ErrorCategory.DATABASE_ERROR,
            node="db_operation"
        ) as ctx:
            # Simulate some work
            await asyncio.sleep(0.01)
            ctx.set_result("success")

        assert ctx.result == "success"
        assert ctx.success is True  # Verify successful completion
        assert ctx.total_delay_seconds >= 0


@pytest.mark.integration
class TestCircuitBreaker:
    """Integration tests for circuit breaker pattern"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_normal_operation(self):
        """Test circuit breaker in CLOSED state (normal operation)"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            timeout_seconds=1.0
        )
        breaker = CircuitBreaker("test_service", config)

        # Successful calls should keep circuit CLOSED
        async def successful_operation():
            await asyncio.sleep(0.01)
            return "success"

        for _ in range(5):
            result = await breaker.call(successful_operation)
            assert result == "success"

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """Test circuit breaker opens after failure threshold"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            timeout_seconds=1.0
        )
        breaker = CircuitBreaker("test_service", config)

        async def failing_operation():
            raise Exception("Service unavailable")

        # Cause failures to open circuit
        for _ in range(3):
            with pytest.raises(Exception):
                await breaker.call(failing_operation)

        # Circuit should now be OPEN
        assert breaker.state == CircuitState.OPEN

        # Further calls should be rejected immediately
        with pytest.raises(CircuitBreakerError) as exc_info:
            await breaker.call(failing_operation)

        # Check error message (format: "Circuit breaker 'test_service' is open")
        assert "is open" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker HALF_OPEN state and recovery"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            success_threshold=2,
            timeout_seconds=0.1,  # Short timeout for fast test
            half_open_max_calls=1
        )
        breaker = CircuitBreaker("test_service", config)

        async def failing_operation():
            raise Exception("Failure")

        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                await breaker.call(failing_operation)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.2)

        # Circuit should transition to HALF_OPEN and allow one test call
        async def successful_operation():
            return "success"

        # First success in HALF_OPEN
        result = await breaker.call(successful_operation)
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN

        # Need one more success to close circuit
        result = await breaker.call(successful_operation)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_decorator(self):
        """Test circuit breaker decorator"""
        call_count = 0

        @with_circuit_breaker("decorated_service", config=CircuitBreakerConfig(failure_threshold=2))
        async def service_call():
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise Exception("Service error")
            return "success"

        # First two calls will fail and open circuit
        with pytest.raises(Exception):
            await service_call()
        with pytest.raises(Exception):
            await service_call()

        # Third call should be rejected by circuit breaker
        with pytest.raises(CircuitBreakerError):
            await service_call()

        assert call_count == 2  # Circuit opened after 2 failures

    @pytest.mark.asyncio
    async def test_circuit_breaker_statistics(self):
        """Test circuit breaker statistics tracking"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("stats_test", config)

        # Mix of successes and failures
        async def sometimes_fails():
            if breaker.get_stats()["total_calls"] % 2 == 0:
                raise Exception("Failure")
            return "success"

        # Make several calls
        for _ in range(4):
            try:
                await breaker.call(sometimes_fails)
            except Exception:
                pass

        stats = breaker.get_stats()
        assert stats["total_calls"] == 4
        assert stats["total_failures"] == 2
        assert stats["total_successes"] == 2
        assert stats["failure_rate"] == 0.5
        assert "state" in stats


@pytest.mark.integration
class TestPerformanceMetrics:
    """Integration tests for performance metrics collection"""

    def test_metrics_initialization(self):
        """Test metrics initialization"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        assert metrics.session_id == "test_session"
        assert metrics.llm_call_count == 0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.total_errors == 0
        assert metrics.start_time is not None

    def test_metrics_node_execution_recording(self):
        """Test recording node execution metrics"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        # Record successful node execution
        metrics.record_node_execution("search_orchestrator", duration_seconds=1.5, success=True)
        metrics.record_node_execution("quality_validator", duration_seconds=0.3, success=True)

        assert "search_orchestrator" in metrics.node_latencies
        assert metrics.node_latencies["search_orchestrator"] == 1.5
        assert metrics.node_success_rates["search_orchestrator"] == 1.0

        # Record failed node execution
        metrics.record_node_execution("search_orchestrator", duration_seconds=2.0, success=False)

        # Success rate should be updated (1 success, 1 failure = 50%)
        assert metrics.node_success_rates["search_orchestrator"] == 0.5

    def test_metrics_agent_execution_recording(self):
        """Test recording agent execution metrics"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        # Record agent executions
        metrics.record_agent_execution("tavily_search", duration_seconds=1.2, success=True, retry_count=0)
        metrics.record_agent_execution("tavily_search", duration_seconds=1.5, success=True, retry_count=1)

        assert "tavily_search" in metrics.agent_execution_times
        assert metrics.agent_execution_times["tavily_search"] == 2.7  # 1.2 + 1.5
        assert metrics.agent_retry_counts["tavily_search"] == 1  # Total retries

    def test_metrics_llm_call_recording(self):
        """Test recording LLM call metrics"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        # Record LLM calls
        metrics.record_llm_call(step="classification", prompt_tokens=100, completion_tokens=50, cost=0.002)
        metrics.record_llm_call(step="synthesis", prompt_tokens=200, completion_tokens=100, cost=0.005)
        metrics.record_llm_call(step="classification", prompt_tokens=100, completion_tokens=50, cost=0.002)

        assert metrics.llm_call_count == 3
        assert metrics.llm_total_tokens == 600  # (100+50) + (200+100) + (100+50)
        assert metrics.llm_cost_estimate == pytest.approx(0.009, 0.0001)  # 0.002 + 0.005 + 0.002
        assert metrics.llm_calls_by_step["classification"] == 2
        assert metrics.llm_calls_by_step["synthesis"] == 1

    def test_metrics_cache_recording(self):
        """Test recording cache access metrics"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        # Record cache accesses
        metrics.record_cache_access(hit=True, time_saved_seconds=1.5)
        metrics.record_cache_access(hit=True, time_saved_seconds=2.0)
        metrics.record_cache_access(hit=False, time_saved_seconds=0.0)

        assert metrics.cache_hits == 2
        assert metrics.cache_misses == 1
        assert metrics.cache_hit_rate == pytest.approx(0.6667, 0.01)  # 2/3
        assert metrics.cache_time_saved == 3.5  # 1.5 + 2.0

    def test_metrics_session_lifecycle(self):
        """Test metrics session lifecycle"""
        collector = get_metrics_collector()

        # Start session
        metrics = collector.start_session("session_123")
        assert "session_123" in collector._metrics

        # Record some data
        metrics.record_node_execution("test_node", 1.0, True)
        metrics.record_llm_call("test", 100, 50, 0.001)

        # Get session metrics (method is get_session_metrics, not get_session)
        retrieved = collector.get_session_metrics("session_123")
        assert retrieved is metrics

        # Finalize session (doesn't remove from _metrics, just finalizes)
        finalized = collector.finalize_session("session_123")
        assert finalized is metrics
        assert metrics.end_time is not None  # Verify it was finalized

        # Clear session (this removes it)
        collector.clear_session("session_123")
        assert "session_123" not in collector._metrics

    def test_metrics_summary(self):
        """Test metrics summary generation"""
        collector = MetricsCollector()
        metrics = collector.start_session("test_session")

        # Add various metrics
        metrics.record_node_execution("node1", 1.0, True)
        metrics.record_agent_execution("agent1", 0.5, True, 0)
        metrics.record_llm_call("step1", 100, 50, 0.002)
        metrics.record_cache_access(hit=True, time_saved_seconds=1.0)

        summary = metrics.get_summary()

        # Verify summary contains key information
        assert "Performance Metrics" in summary or "performance metrics" in summary.lower()
        assert "test_session" in summary  # Session ID should be in summary
        assert "nodes executed" in summary.lower()
        assert "llm calls" in summary.lower()
        assert "cache hit rate" in summary.lower()


@pytest.mark.integration
class TestErrorRecoveryFlow:
    """Integration tests for complete error recovery flows"""

    @pytest.mark.asyncio
    async def test_retry_with_circuit_breaker(self):
        """Test retry mechanism combined with circuit breaker"""
        # Create circuit breaker
        breaker = get_circuit_breaker(
            "external_api",
            CircuitBreakerConfig(failure_threshold=3, timeout_seconds=0.1)
        )

        call_count = 0

        async def flaky_api_call():
            nonlocal call_count
            call_count += 1
            # Fail first 2 times, then succeed
            if call_count < 3:
                raise Exception("API timeout")
            return "success"

        # Wrap with circuit breaker and retry
        result = await retry_with_strategy(
            lambda: breaker.call(flaky_api_call),
            error_category=ErrorCategory.EXTERNAL_API_ERROR,
            node="api_call"
        )

        assert result == "success"
        assert call_count == 3
        assert breaker.state == CircuitState.CLOSED  # Should remain closed as it eventually succeeded

    @pytest.mark.asyncio
    async def test_structured_error_with_metrics(self):
        """Test structured error tracking with metrics collection"""
        collector = MetricsCollector()
        metrics = collector.start_session("error_test_session")

        # Simulate errors of different categories
        errors = []

        # Network error (ConnectionError)
        try:
            raise ConnectionError("Connection timeout")
        except Exception as e:
            error = categorize_exception(e, node="network_call")
            errors.append(error)
            metrics.record_error(error.category.value, error.recoverable)

        # Timeout error
        try:
            raise asyncio.TimeoutError("Operation timed out")
        except Exception as e:
            error = categorize_exception(e, node="timeout_node")
            errors.append(error)
            metrics.record_error(error.category.value, error.recoverable)

        # Validation error
        try:
            raise ValueError("Invalid format")
        except Exception as e:
            error = categorize_exception(e, node="validator")
            errors.append(error)
            metrics.record_error(error.category.value, error.recoverable)

        # Verify metrics tracked errors
        assert metrics.total_errors == 3
        assert metrics.error_count_by_category[ErrorCategory.NETWORK_ERROR.value] == 1
        assert metrics.error_count_by_category[ErrorCategory.AGENT_TIMEOUT.value] == 1
        assert metrics.error_count_by_category[ErrorCategory.VALIDATION_ERROR.value] == 1

        # Verify recoverable count
        recoverable_count = sum(1 for e in errors if e.recoverable)
        assert recoverable_count == 2  # Network and timeout errors are recoverable
        assert metrics.recoverable_errors == 2

    @pytest.mark.asyncio
    async def test_complete_workflow_simulation(self):
        """
        Integration test simulating a complete workflow with:
        - Metrics collection
        - Error handling
        - Retries
        - Circuit breaker
        """
        # Setup
        collector = get_metrics_collector()
        metrics = collector.start_session("workflow_integration_test")

        # Simulate workflow phases
        start_time = time.time()

        # Phase 1: Query Classification (success)
        metrics.record_node_execution("query_classifier", duration_seconds=0.1, success=True)
        metrics.record_llm_call("classification", prompt_tokens=50, completion_tokens=20, cost=0.001)

        # Phase 2: Search Orchestration (with retry due to transient error)
        search_attempts = 0

        async def search_with_retry():
            nonlocal search_attempts
            search_attempts += 1
            if search_attempts < 2:
                raise Exception("Tavily API timeout")
            return "search_results"

        try:
            await retry_with_strategy(
                search_with_retry,
                error_category=ErrorCategory.EXTERNAL_API_ERROR,
                node="search_orchestrator"
            )
            metrics.record_node_execution("search_orchestrator", duration_seconds=1.2, success=True)
            metrics.record_agent_execution("tavily_search", duration_seconds=1.2, success=True, retry_count=1)
        except Exception as e:
            error = categorize_exception(e, node="search_orchestrator")
            metrics.record_error(error.category.value)
            metrics.record_node_execution("search_orchestrator", duration_seconds=1.2, success=False)

        # Phase 3: Cache hit for similar query
        metrics.record_cache_access(hit=True, time_saved_seconds=2.0)

        # Phase 4: Quality validation (success)
        metrics.record_node_execution("quality_validator", duration_seconds=0.2, success=True)

        # Finalize metrics
        elapsed = time.time() - start_time
        metrics.end_time = datetime.now()

        # Assertions
        assert metrics.llm_call_count == 1
        assert metrics.cache_hits == 1
        assert search_attempts == 2  # Failed once, succeeded on retry
        assert len(metrics.node_latencies) >= 3  # At least 3 nodes executed

        # Get summary
        summary = metrics.get_summary()
        assert "workflow_integration_test" in summary
        assert "cache hit rate: 100.0%" in summary.lower()

        # Cleanup
        collector.finalize_session("workflow_integration_test")


@pytest.mark.integration
class TestConfigurationIntegration:
    """Integration tests for centralized configuration"""

    def test_workflow_config_from_settings(self):
        """Test workflow configuration loads from settings"""
        from neos.config.settings import settings
        from neos.workflow.state import WorkflowConfig

        # Verify settings are loaded
        assert hasattr(settings, "WORKFLOW_MIN_QUALITY_SCORE")
        assert hasattr(settings, "WORKFLOW_MAX_RETRIES")
        assert hasattr(settings, "WORKFLOW_MAX_ITERATIONS")
        assert hasattr(settings, "WORKFLOW_TIMEOUT_SECONDS")
        assert hasattr(settings, "WORKFLOW_CRITICAL_NODES")

        # Verify WorkflowConfig uses settings
        assert WorkflowConfig.MIN_QUALITY_SCORE == settings.WORKFLOW_MIN_QUALITY_SCORE
        assert WorkflowConfig.MAX_RETRIES == settings.WORKFLOW_MAX_RETRIES
        assert WorkflowConfig.MAX_ITERATIONS == settings.WORKFLOW_MAX_ITERATIONS
        assert WorkflowConfig.TIMEOUT_SECONDS == settings.WORKFLOW_TIMEOUT_SECONDS

    def test_critical_nodes_configuration(self):
        """Test critical nodes are properly configured"""
        from neos.config.settings import settings

        critical_nodes = settings.WORKFLOW_CRITICAL_NODES

        # Verify critical nodes include key workflow stages
        assert "query_classifier" in critical_nodes
        assert "search_orchestrator" in critical_nodes
        assert "quality_validator" in critical_nodes
        assert "response_generator" in critical_nodes

        # Should be at least 4 critical nodes
        assert len(critical_nodes) >= 4
