"""
Enterprise Metrics Collection for NEOS

Prometheus-compatible metrics for comprehensive monitoring:
- Request/response metrics (RED: Rate, Error, Duration)
- Agent execution metrics
- Workflow performance
- Resource utilization
- Business metrics

Integration with Prometheus, Grafana, and alerting systems.
"""

from typing import Optional
import time
from functools import wraps
import asyncio

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)


class EnterpriseMetricsCollector:
    """
    Enterprise-grade metrics collector for NEOS multi-agent system.

    Collects and exposes metrics in Prometheus format for:
    - API requests and responses
    - Agent execution performance
    - Workflow orchestration
    - LLM API calls
    - Error rates and types
    - Resource utilization
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        Initialize metrics collector.

        Args:
            registry: Custom Prometheus registry (uses default if None)
        """
        self.registry = registry or CollectorRegistry()

        # === API Metrics (RED) ===

        # Request rate
        self.http_requests_total = Counter(
            'neos_http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )

        # Request duration
        self.http_request_duration_seconds = Histogram(
            'neos_http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint'],
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=self.registry
        )

        # Active requests
        self.http_requests_in_progress = Gauge(
            'neos_http_requests_in_progress',
            'Number of HTTP requests in progress',
            ['method', 'endpoint'],
            registry=self.registry
        )

        # === Workflow Metrics ===

        self.workflow_executions_total = Counter(
            'neos_workflow_executions_total',
            'Total workflow executions',
            ['workflow_type', 'status'],
            registry=self.registry
        )

        self.workflow_duration_seconds = Histogram(
            'neos_workflow_duration_seconds',
            'Workflow execution duration in seconds',
            ['workflow_type'],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
            registry=self.registry
        )

        self.workflow_quality_score = Histogram(
            'neos_workflow_quality_score',
            'Workflow response quality score',
            ['workflow_type'],
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=self.registry
        )

        self.workflow_retry_count = Counter(
            'neos_workflow_retry_count',
            'Number of workflow retries',
            ['workflow_type', 'reason'],
            registry=self.registry
        )

        # === Agent Metrics ===

        self.agent_executions_total = Counter(
            'neos_agent_executions_total',
            'Total agent executions',
            ['agent_type', 'status'],
            registry=self.registry
        )

        self.agent_duration_seconds = Histogram(
            'neos_agent_duration_seconds',
            'Agent execution duration in seconds',
            ['agent_type'],
            buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
            registry=self.registry
        )

        self.agent_errors_total = Counter(
            'neos_agent_errors_total',
            'Total agent execution errors',
            ['agent_type', 'error_type'],
            registry=self.registry
        )

        # === Durable Coding Loop Metrics ===

        self.coding_phase_duration_seconds = Histogram(
            "coding_phase_duration_seconds",
            "Durable coding phase duration in seconds",
            ["phase"],
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60, 300),
            registry=self.registry,
        )
        self.coding_checkpoint_total = Counter(
            "coding_checkpoint_total",
            "Committed durable coding checkpoints",
            ["phase"],
            registry=self.registry,
        )
        self.coding_model_turn_total = Counter(
            "coding_model_turn_total",
            "Coding model turn outcomes",
            ["provider", "outcome"],
            registry=self.registry,
        )
        self.coding_tool_execution_total = Counter(
            "coding_tool_execution_total",
            "Coding tool execution outcomes",
            ["tool", "outcome"],
            registry=self.registry,
        )
        self.subagent_advance_total = Counter(
            "subagent_advance_total",
            "Subagent safe-point outcomes",
            ["spec", "parent_kind", "outcome"],
            registry=self.registry,
        )
        self.subagent_advance_seconds = Histogram(
            "subagent_advance_seconds",
            "Subagent advance duration in seconds",
            ["spec", "parent_kind"],
            buckets=(0.05, 0.2, 0.5, 1, 2, 5, 15, 30, 60, 120),
            registry=self.registry,
        )
        self.subagent_tokens_total = Counter(
            "subagent_tokens_total",
            "Subagent token usage",
            ["spec", "parent_kind", "direction"],
            registry=self.registry,
        )
        self.subagent_cost_micros_total = Counter(
            "subagent_cost_micros_total",
            "Subagent cost in micros",
            ["spec", "parent_kind", "provider"],
            registry=self.registry,
        )
        self.subagent_fold_chars = Histogram(
            "subagent_fold_chars",
            "Folded subagent report size in characters",
            ["spec"],
            buckets=(256, 512, 1000, 2000, 4000, 8000, 16384),
            registry=self.registry,
        )
        self.subagent_cas_mismatch_total = Counter(
            "subagent_cas_mismatch_total",
            "Subagent checkpoint CAS mismatches",
            ["parent_kind"],
            registry=self.registry,
        )
        self.subagent_live_children = Histogram(
            "subagent_live_children",
            "Live subagent children after a parent spawn delivery",
            ["parent_kind", "spec"],
            buckets=(0, 1, 2, 3, 4),
            registry=self.registry,
        )
        self.subagent_policy_capped_total = Counter(
            "subagent_policy_capped_total",
            "Spawn attempts rejected because a child is already active",
            ["parent_kind"],
            registry=self.registry,
        )
        self.subagent_fold_rollup_tokens_total = Counter(
            "subagent_fold_rollup_tokens_total",
            "Parent-priced child tokens rolled into the parent on child_fold",
            ["parent_kind", "direction"],
            registry=self.registry,
        )
        self.subagent_fold_rollup_cost_micros_total = Counter(
            "subagent_fold_rollup_cost_micros_total",
            "Parent-priced child cost in micros rolled into the parent on child_fold",
            ["parent_kind", "provider"],
            registry=self.registry,
        )
        self.subagent_adopt_error_total = Counter(
            "subagent_adopt_error_total",
            "Spawn claim adopt/complete failures skipped so the parent does not crash",
            ["parent_kind", "op"],
            registry=self.registry,
        )
        self.coding_sandbox_lifecycle_seconds = Histogram(
            "coding_sandbox_lifecycle_seconds",
            "Coding sandbox lifecycle operation duration",
            ["provider", "operation", "outcome"],
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60),
            registry=self.registry,
        )
        self.coding_sandbox_stream_total = Counter(
            "coding_sandbox_stream_total",
            "Coding sandbox stream outcomes",
            ["stream", "outcome"],
            registry=self.registry,
        )
        self.coding_sandbox_active = Gauge(
            "coding_sandbox_active",
            "Active coding sandboxes by provider and state",
            ["provider", "state"],
            registry=self.registry,
        )
        self.coding_sandbox_operation_total = Counter(
            "coding_sandbox_operation_total",
            "Coding sandbox operation outcomes",
            ["provider", "operation", "outcome", "error_code"],
            registry=self.registry,
        )
        self.coding_sandbox_admission_total = Counter(
            "coding_sandbox_admission_total",
            "Managed sandbox admission decisions",
            ["decision", "reason"],
            registry=self.registry,
        )
        self.coding_sandbox_allocation_total = Counter(
            "coding_sandbox_allocation_total",
            "Managed sandbox allocation outcomes",
            ["provider", "region", "outcome", "error_code"],
            registry=self.registry,
        )
        self.coding_sandbox_allocation_duration_seconds = Histogram(
            "coding_sandbox_allocation_duration_seconds",
            "Managed sandbox allocation duration in seconds",
            ["provider", "region", "outcome"],
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60, 300),
            registry=self.registry,
        )
        self.coding_sandbox_provider_circuit = Gauge(
            "coding_sandbox_provider_circuit",
            "Managed sandbox provider circuit state",
            ["provider", "region", "state"],
            registry=self.registry,
        )
        self.coding_sandbox_cleanup_age_seconds = Gauge(
            "coding_sandbox_cleanup_age_seconds",
            "Age of managed sandbox cleanup work in seconds",
            ["provider", "region"],
            registry=self.registry,
        )
        self.coding_sandbox_cleanup_total = Counter(
            "coding_sandbox_cleanup_total",
            "Managed sandbox cleanup outcomes",
            ["provider", "region", "outcome", "error_code"],
            registry=self.registry,
        )
        self.coding_sandbox_archive_total = Counter(
            "coding_sandbox_archive_total",
            "Managed sandbox archive operation outcomes",
            ["provider", "operation", "outcome", "error_code"],
            registry=self.registry,
        )
        self.coding_steering_latency_seconds = Histogram(
            "coding_steering_latency_seconds",
            "Time from steering request to safe-point application",
            ["outcome"],
            registry=self.registry,
        )
        self.coding_resume_total = Counter(
            "coding_resume_total",
            "Durable coding loop resume attempts",
            ["outcome"],
            registry=self.registry,
        )
        # Q8b: 스레드는 대화를 막지 못한다 -- 실패는 삼키되 여기서 센다.
        self.standing_thread_failures_total = Counter(
            "standing_thread_failures_total",
            "Standing agent thread reads/writes that failed and were skipped",
            ["op"],
            registry=self.registry,
        )
        self.coding_lease_contention_total = Counter(
            "coding_lease_contention_total",
            "Durable coding execution lease outcomes",
            ["outcome"],
            registry=self.registry,
        )
        self.coding_supervisor_tasks_total = Counter(
            "coding_supervisor_tasks_total",
            "Development coding supervisor task outcomes",
            ["outcome"],
            registry=self.registry,
        )
        self.coding_supervisor_retry_total = Counter(
            "coding_supervisor_retry_total",
            "Development coding supervisor retries",
            ["reason"],
            registry=self.registry,
        )
        self.coding_supervisor_active_tasks = Gauge(
            "coding_supervisor_active_tasks",
            "Active development coding supervisor tasks",
            registry=self.registry,
        )
        self.coding_worker_tasks_total = Counter(
            "coding_worker_tasks_total",
            "Coding Celery worker task outcomes",
            ["outcome"],
            registry=self.registry,
        )
        self.coding_worker_retry_total = Counter(
            "coding_worker_retry_total",
            "Coding Celery worker retries",
            ["reason"],
            registry=self.registry,
        )
        self.coding_worker_active_tasks = Gauge(
            "coding_worker_active_tasks",
            "Active coding Celery worker tasks",
            registry=self.registry,
        )
        self.coding_dispatch_total = Counter(
            "coding_dispatch_total",
            "Coding task dispatch attempts",
            ["source", "outcome"],
            registry=self.registry,
        )
        self.coding_reconciliation_tasks_total = Counter(
            "coding_reconciliation_tasks_total",
            "Coding reconciliation task outcomes",
            ["outcome"],
            registry=self.registry,
        )
        self.coding_approval_total = Counter(
            "coding_approval_total",
            "Coding tool approval lifecycle outcomes",
            ["risk", "outcome"],
            registry=self.registry,
        )
        self.coding_approval_latency_seconds = Histogram(
            "coding_approval_latency_seconds",
            "Coding tool approval decision latency",
            ["outcome"],
            registry=self.registry,
        )

        # === LLM API Metrics ===

        self.llm_calls_total = Counter(
            'neos_llm_calls_total',
            'Total LLM API calls',
            ['provider', 'model', 'status'],
            registry=self.registry
        )

        self.llm_tokens_used = Counter(
            'neos_llm_tokens_used',
            'Total tokens used in LLM calls',
            ['provider', 'model', 'token_type'],  # prompt, completion
            registry=self.registry
        )

        self.llm_call_duration_seconds = Histogram(
            'neos_llm_call_duration_seconds',
            'LLM API call duration in seconds',
            ['provider', 'model'],
            buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60),
            registry=self.registry
        )

        self.llm_cost_usd = Counter(
            'neos_llm_cost_usd',
            'Estimated LLM cost in USD',
            ['provider', 'model'],
            registry=self.registry
        )

        # 가격을 모르는 모델의 호출 수. 이 모델들의 비용은 0으로 집계되므로
        # neos_llm_cost_usd가 실제보다 낮게 나온다. 0이 아니면 해당 모델의
        # 가격을 llm_model_pricing DB나 neos/config/models.yaml에 넣어야 한다.
        self.llm_unpriced_calls_total = Counter(
            'neos_llm_unpriced_calls_total',
            'LLM cost lookups with no known price (cost aggregated as zero)',
            ['provider', 'model'],
            registry=self.registry
        )

        # Catalog identity. Labels are cardinality-safe: never a raw model id.
        self.catalog_resolve_total = Counter(
            "neos_catalog_resolve_total",
            "Catalog canonicalize results by identity source",
            ["source"],
            registry=self.registry,
        )
        # Chat effort source per turn. Label is the source only, never a model id.
        self.chat_effort_resolved_total = Counter(
            "neos_chat_effort_resolved_total",
            "Chat turns by where their effort came from",
            ["source"],
            registry=self.registry,
        )
        self.catalog_remap_total = Counter(
            "neos_catalog_remap_total",
            "Catalog remaps applied to a user/cookie string",
            registry=self.registry,
        )
        self.catalog_live_unknown_total = Counter(
            "neos_catalog_live_unknown_total",
            "Live Anthropic ids not present in the YAML catalog",
            registry=self.registry,
        )

        # === Database Metrics ===

        self.db_queries_total = Counter(
            'neos_db_queries_total',
            'Total database queries',
            ['operation', 'table', 'status'],
            registry=self.registry
        )

        self.db_query_duration_seconds = Histogram(
            'neos_db_query_duration_seconds',
            'Database query duration in seconds',
            ['operation', 'table'],
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 10),
            registry=self.registry
        )

        self.db_connections_active = Gauge(
            'neos_db_connections_active',
            'Number of active database connections',
            registry=self.registry
        )

        self.db_connections_idle = Gauge(
            'neos_db_connections_idle',
            'Number of idle database connections',
            registry=self.registry
        )

        # === Cache Metrics ===

        self.cache_hits_total = Counter(
            'neos_cache_hits_total',
            'Total cache hits',
            ['cache_type'],
            registry=self.registry
        )

        self.cache_misses_total = Counter(
            'neos_cache_misses_total',
            'Total cache misses',
            ['cache_type'],
            registry=self.registry
        )

        self.cache_size_bytes = Gauge(
            'neos_cache_size_bytes',
            'Cache size in bytes',
            ['cache_type'],
            registry=self.registry
        )

        # === Search Metrics ===

        self.search_queries_total = Counter(
            'neos_search_queries_total',
            'Total search queries',
            ['search_type', 'status'],
            registry=self.registry
        )

        self.search_results_count = Histogram(
            'neos_search_results_count',
            'Number of search results returned',
            ['search_type'],
            buckets=(0, 1, 5, 10, 20, 50, 100, 200, 500),
            registry=self.registry
        )

        self.search_duration_seconds = Histogram(
            'neos_search_duration_seconds',
            'Search execution duration in seconds',
            ['search_type'],
            buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 300, 600),
            registry=self.registry
        )

        # === Resource Metrics ===

        self.active_sessions = Gauge(
            'neos_active_sessions',
            'Number of active user sessions',
            registry=self.registry
        )

        self.memory_usage_bytes = Gauge(
            'neos_memory_usage_bytes',
            'Memory usage in bytes',
            ['type'],  # rss, vms, shared
            registry=self.registry
        )

        # === Business Metrics ===

        self.user_queries_total = Counter(
            'neos_user_queries_total',
            'Total user queries',
            ['user_type', 'query_complexity'],
            registry=self.registry
        )

        self.user_satisfaction_score = Histogram(
            'neos_user_satisfaction_score',
            'User satisfaction score (if provided)',
            buckets=(1, 2, 3, 4, 5),
            registry=self.registry
        )

        # === Ray 분산 처리 메트릭 (Phase 4) ===

        self.ray_pool_utilization = Gauge(
            'neos_ray_executor_pool_utilization',
            'Ray executor pool utilization ratio (active workers / total)',
            ['pool_name'],
            registry=self.registry
        )

        self.ray_task_duration_seconds = Histogram(
            'neos_ray_task_duration_seconds',
            'Ray distributed task execution duration in seconds',
            ['task_type', 'level'],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600),
            registry=self.registry
        )

        self.ray_parallel_speedup_ratio = Gauge(
            'neos_ray_parallel_speedup_ratio',
            'Estimated speedup ratio vs sequential execution (parallel_time / sequential_time)',
            registry=self.registry
        )

        self.ray_actor_restarts_total = Counter(
            'neos_ray_actor_restarts_total',
            'Total Ray Actor restarts (fault recovery indicator)',
            ['actor_type'],
            registry=self.registry
        )

        self.ray_level_tasks_parallel = Histogram(
            'neos_ray_level_tasks_parallel',
            'Number of tasks executed in parallel per level',
            buckets=(1, 2, 3, 4, 5, 6, 8, 10),
            registry=self.registry
        )

        # Internal tracking
        self._request_start_times = {}

    # === Decorator Methods ===

    def track_request(self, method: str, endpoint: str):
        """
        Decorator to track HTTP request metrics.

        Usage:
            @metrics.track_request("GET", "/api/v1/query")
            async def query_endpoint():
                ...
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Increment in-progress gauge
                self.http_requests_in_progress.labels(
                    method=method,
                    endpoint=endpoint
                ).inc()

                start_time = time.time()

                try:
                    # Execute function
                    result = await func(*args, **kwargs)
                    status = "200"  # Assume success

                    # Try to extract status from result
                    if isinstance(result, dict) and "status_code" in result:
                        status = str(result["status_code"])

                    return result

                except Exception:
                    status = "500"
                    raise

                finally:
                    # Record duration
                    duration = time.time() - start_time
                    self.http_request_duration_seconds.labels(
                        method=method,
                        endpoint=endpoint
                    ).observe(duration)

                    # Increment total requests
                    self.http_requests_total.labels(
                        method=method,
                        endpoint=endpoint,
                        status=status
                    ).inc()

                    # Decrement in-progress gauge
                    self.http_requests_in_progress.labels(
                        method=method,
                        endpoint=endpoint
                    ).dec()

            return wrapper
        return decorator

    def track_workflow(self, workflow_type: str = "main"):
        """
        Decorator to track workflow execution metrics.

        Usage:
            @metrics.track_workflow("deep_research")
            async def execute_deep_research():
                ...
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                status = "success"

                try:
                    result = await func(*args, **kwargs)

                    # Extract quality score if available
                    if isinstance(result, dict):
                        quality_score = result.get("quality_score", 0.8)
                        self.workflow_quality_score.labels(
                            workflow_type=workflow_type
                        ).observe(quality_score)

                        # Track retries
                        retry_count = result.get("retry_count", 0)
                        if retry_count > 0:
                            self.workflow_retry_count.labels(
                                workflow_type=workflow_type,
                                reason="low_quality"
                            ).inc(retry_count)

                    return result

                except Exception:
                    status = "error"
                    raise

                finally:
                    # Record duration
                    duration = time.time() - start_time
                    self.workflow_duration_seconds.labels(
                        workflow_type=workflow_type
                    ).observe(duration)

                    # Increment total executions
                    self.workflow_executions_total.labels(
                        workflow_type=workflow_type,
                        status=status
                    ).inc()

            return wrapper
        return decorator

    def track_agent(self, agent_type: str):
        """
        Decorator to track agent execution metrics.

        Usage:
            @metrics.track_agent("deep_research")
            async def execute_agent():
                ...
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                status = "success"

                try:
                    result = await func(*args, **kwargs)
                    return result

                except Exception as e:
                    status = "error"
                    error_type = type(e).__name__

                    self.agent_errors_total.labels(
                        agent_type=agent_type,
                        error_type=error_type
                    ).inc()

                    raise

                finally:
                    # Record duration
                    duration = time.time() - start_time
                    self.agent_duration_seconds.labels(
                        agent_type=agent_type
                    ).observe(duration)

                    # Increment total executions
                    self.agent_executions_total.labels(
                        agent_type=agent_type,
                        status=status
                    ).inc()

            return wrapper
        return decorator

    # === Manual Recording Methods ===

    def record_llm_call(
        self,
        provider: str,
        model: str,
        duration: float,
        prompt_tokens: int,
        completion_tokens: int,
        status: str = "success",
        cost_usd: float = 0.0
    ):
        """Record LLM API call metrics."""
        self.llm_calls_total.labels(
            provider=provider,
            model=model,
            status=status
        ).inc()

        self.llm_call_duration_seconds.labels(
            provider=provider,
            model=model
        ).observe(duration)

        self.llm_tokens_used.labels(
            provider=provider,
            model=model,
            token_type="prompt"
        ).inc(prompt_tokens)

        self.llm_tokens_used.labels(
            provider=provider,
            model=model,
            token_type="completion"
        ).inc(completion_tokens)

        if cost_usd > 0:
            self.llm_cost_usd.labels(
                provider=provider,
                model=model
            ).inc(cost_usd)

    def record_cache_hit(self, cache_type: str):
        """Record cache hit."""
        self.cache_hits_total.labels(cache_type=cache_type).inc()

    def record_cache_miss(self, cache_type: str):
        """Record cache miss."""
        self.cache_misses_total.labels(cache_type=cache_type).inc()

    def set_active_sessions(self, count: int):
        """Set number of active sessions."""
        self.active_sessions.set(count)

    def set_db_connections(self, active: int, idle: int):
        """Set database connection counts."""
        self.db_connections_active.set(active)
        self.db_connections_idle.set(idle)

    def record_search_query(
        self,
        search_type: str,
        duration: float,
        results_count: int,
        status: str = "success"
    ):
        """Record search query metrics."""
        self.search_queries_total.labels(
            search_type=search_type,
            status=status
        ).inc()

        self.search_duration_seconds.labels(
            search_type=search_type
        ).observe(duration)

        self.search_results_count.labels(
            search_type=search_type
        ).observe(results_count)

    def record_user_query(
        self,
        user_type: str = "free",
        query_complexity: str = "medium"
    ):
        """Record user query for business metrics."""
        self.user_queries_total.labels(
            user_type=user_type,
            query_complexity=query_complexity
        ).inc()

    def export_metrics(self) -> bytes:
        """
        Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics as bytes
        """
        return generate_latest(self.registry)

    def get_content_type(self) -> str:
        """Get Prometheus content type for HTTP response."""
        return CONTENT_TYPE_LATEST

    async def collect_system_metrics(self):
        """
        Collect system-level metrics periodically.
        Should be run as a background task.
        """
        import psutil

        while True:
            try:
                # Memory metrics
                process = psutil.Process()
                memory_info = process.memory_info()

                self.memory_usage_bytes.labels(type="rss").set(memory_info.rss)
                self.memory_usage_bytes.labels(type="vms").set(memory_info.vms)

                # Wait before next collection
                await asyncio.sleep(15)  # Collect every 15 seconds

            except Exception as e:
                print(f"[WARNING] Failed to collect system metrics: {e}")
                await asyncio.sleep(60)  # Wait longer on error


# Global metrics collector instance
_metrics_collector: Optional[EnterpriseMetricsCollector] = None


def get_metrics_collector() -> EnterpriseMetricsCollector:
    """
    Get or create global metrics collector instance.

    Returns:
        EnterpriseMetricsCollector instance
    """
    global _metrics_collector

    if _metrics_collector is None:
        _metrics_collector = EnterpriseMetricsCollector()

    return _metrics_collector


# Convenience aliases
metrics = get_metrics_collector()
track_request = metrics.track_request
track_workflow = metrics.track_workflow

# ============================================================================
# Contextual Retrieval Metrics (모듈 레벨 — contextual_retrieval.py에서 import 가능)
# ============================================================================

contextual_retrieval_chunks_total = Counter(
    "contextual_retrieval_chunks_total",
    "Contextual Retrieval로 처리된 청크 수",
    ["status"],  # success, failed, fallback
)

contextual_retrieval_cache_hits_total = Counter(
    "contextual_retrieval_cache_hits_total",
    "Anthropic Prompt Cache 히트 횟수",
)

contextual_retrieval_cost_usd_total = Counter(
    "contextual_retrieval_cost_usd_total",
    "Contextual Retrieval API 호출 총 비용 (USD)",
)

contextual_retrieval_duration_seconds = Histogram(
    "contextual_retrieval_duration_seconds",
    "문서 전체 청크의 컨텍스트 생성 소요 시간 (초)",
    buckets=[5, 10, 30, 60, 120, 300],
)
track_agent = metrics.track_agent
