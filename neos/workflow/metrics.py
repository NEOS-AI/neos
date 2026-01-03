"""Performance metrics tracking for workflow system

Provides detailed metrics collection for monitoring, debugging, and optimization.
Tracks node-level latencies, agent performance, LLM costs, and cache effectiveness.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import time


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for workflow execution

    Tracks metrics across multiple dimensions:
    - Node-level: Latency and success rates per workflow node
    - Agent-level: Execution times and retry counts per agent
    - LLM-level: Call counts, token usage, and cost estimates
    - Cache-level: Hit rates and performance impact
    - Quality-level: Score history and retry reasons

    Attributes:
        session_id: Unique session identifier
        start_time: Workflow start timestamp
        end_time: Workflow end timestamp (set on completion)

        # Node metrics
        node_latencies: Latency in seconds per node
        node_success_rates: Success rate (0.0-1.0) per node
        node_execution_count: Number of executions per node

        # Agent metrics
        agent_execution_times: Total execution time per agent
        agent_retry_counts: Number of retries per agent
        agent_success_counts: Number of successful executions per agent
        agent_failure_counts: Number of failed executions per agent

        # LLM metrics
        llm_call_count: Total LLM API calls
        llm_total_tokens: Total tokens consumed (prompt + completion)
        llm_prompt_tokens: Total prompt tokens
        llm_completion_tokens: Total completion tokens
        llm_cost_estimate: Estimated cost in USD
        llm_calls_by_step: LLM calls breakdown by workflow step

        # Cache metrics
        cache_hits: Number of cache hits
        cache_misses: Number of cache misses
        cache_hit_rate: Cache hit rate (0.0-1.0)
        cache_time_saved: Estimated time saved by cache (seconds)

        # Quality metrics
        quality_score_history: Quality scores over retries
        retry_reasons: Reasons for retries
        final_quality_score: Final quality score

        # Error metrics (from structured errors)
        error_count_by_category: Error counts by category
        total_errors: Total number of errors
        recoverable_errors: Number of recoverable errors

        # Overall metrics
        total_duration_ms: Total workflow duration in milliseconds
        total_retries: Total number of retries across all components
    """

    session_id: str
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Node metrics
    node_latencies: Dict[str, float] = field(default_factory=dict)
    node_success_rates: Dict[str, float] = field(default_factory=dict)
    node_execution_count: Dict[str, int] = field(default_factory=dict)

    # Agent metrics
    agent_execution_times: Dict[str, float] = field(default_factory=dict)
    agent_retry_counts: Dict[str, int] = field(default_factory=dict)
    agent_success_counts: Dict[str, int] = field(default_factory=dict)
    agent_failure_counts: Dict[str, int] = field(default_factory=dict)

    # LLM metrics
    llm_call_count: int = 0
    llm_total_tokens: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_cost_estimate: float = 0.0
    llm_calls_by_step: Dict[str, int] = field(default_factory=dict)

    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    cache_time_saved: float = 0.0

    # Quality metrics
    quality_score_history: List[float] = field(default_factory=list)
    retry_reasons: List[str] = field(default_factory=list)
    final_quality_score: Optional[float] = None

    # Error metrics
    error_count_by_category: Dict[str, int] = field(default_factory=dict)
    total_errors: int = 0
    recoverable_errors: int = 0

    # Overall metrics
    total_duration_ms: Optional[int] = None
    total_retries: int = 0

    def record_node_execution(self, node_name: str, duration_seconds: float, success: bool):
        """Record execution metrics for a workflow node"""
        # Update latency (running average)
        if node_name in self.node_latencies:
            count = self.node_execution_count[node_name]
            avg = self.node_latencies[node_name]
            self.node_latencies[node_name] = (avg * count + duration_seconds) / (count + 1)
        else:
            self.node_latencies[node_name] = duration_seconds

        # Update execution count
        self.node_execution_count[node_name] = self.node_execution_count.get(node_name, 0) + 1

        # Update success rate
        count = self.node_execution_count[node_name]
        if node_name in self.node_success_rates:
            current_rate = self.node_success_rates[node_name]
            # Calculate new success rate
            successful = int(current_rate * (count - 1)) + (1 if success else 0)
            self.node_success_rates[node_name] = successful / count
        else:
            self.node_success_rates[node_name] = 1.0 if success else 0.0

    def record_agent_execution(
        self,
        agent_name: str,
        duration_seconds: float,
        success: bool,
        retry_count: int = 0
    ):
        """Record execution metrics for an agent"""
        # Execution time
        self.agent_execution_times[agent_name] = (
            self.agent_execution_times.get(agent_name, 0.0) + duration_seconds
        )

        # Success/failure counts
        if success:
            self.agent_success_counts[agent_name] = (
                self.agent_success_counts.get(agent_name, 0) + 1
            )
        else:
            self.agent_failure_counts[agent_name] = (
                self.agent_failure_counts.get(agent_name, 0) + 1
            )

        # Retry counts
        if retry_count > 0:
            self.agent_retry_counts[agent_name] = (
                self.agent_retry_counts.get(agent_name, 0) + retry_count
            )
            self.total_retries += retry_count

    def record_llm_call(
        self,
        step: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float
    ):
        """Record LLM API call metrics"""
        self.llm_call_count += 1
        self.llm_prompt_tokens += prompt_tokens
        self.llm_completion_tokens += completion_tokens
        self.llm_total_tokens += (prompt_tokens + completion_tokens)
        self.llm_cost_estimate += cost

        # Track calls by step
        self.llm_calls_by_step[step] = self.llm_calls_by_step.get(step, 0) + 1

    def record_cache_access(self, hit: bool, time_saved_seconds: float = 0.0):
        """Record cache hit/miss"""
        if hit:
            self.cache_hits += 1
            self.cache_time_saved += time_saved_seconds
        else:
            self.cache_misses += 1

        # Update hit rate
        total = self.cache_hits + self.cache_misses
        self.cache_hit_rate = self.cache_hits / total if total > 0 else 0.0

    def record_quality_score(self, score: float, retry_reason: Optional[str] = None):
        """Record quality score"""
        self.quality_score_history.append(score)
        if retry_reason:
            self.retry_reasons.append(retry_reason)

    def record_error(self, error_category: str, recoverable: bool):
        """Record error occurrence"""
        self.error_count_by_category[error_category] = (
            self.error_count_by_category.get(error_category, 0) + 1
        )
        self.total_errors += 1
        if recoverable:
            self.recoverable_errors += 1

    def finalize(self):
        """Finalize metrics at workflow completion"""
        self.end_time = datetime.utcnow()
        duration = (self.end_time - self.start_time).total_seconds()
        self.total_duration_ms = int(duration * 1000)

        # Set final quality score
        if self.quality_score_history:
            self.final_quality_score = self.quality_score_history[-1]

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_duration_ms": self.total_duration_ms,

            # Node metrics
            "node_metrics": {
                "latencies": self.node_latencies,
                "success_rates": self.node_success_rates,
                "execution_counts": self.node_execution_count,
            },

            # Agent metrics
            "agent_metrics": {
                "execution_times": self.agent_execution_times,
                "retry_counts": self.agent_retry_counts,
                "success_counts": self.agent_success_counts,
                "failure_counts": self.agent_failure_counts,
            },

            # LLM metrics
            "llm_metrics": {
                "call_count": self.llm_call_count,
                "total_tokens": self.llm_total_tokens,
                "prompt_tokens": self.llm_prompt_tokens,
                "completion_tokens": self.llm_completion_tokens,
                "cost_estimate_usd": self.llm_cost_estimate,
                "calls_by_step": self.llm_calls_by_step,
            },

            # Cache metrics
            "cache_metrics": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": self.cache_hit_rate,
                "time_saved_seconds": self.cache_time_saved,
            },

            # Quality metrics
            "quality_metrics": {
                "score_history": self.quality_score_history,
                "retry_reasons": self.retry_reasons,
                "final_score": self.final_quality_score,
            },

            # Error metrics
            "error_metrics": {
                "by_category": self.error_count_by_category,
                "total_errors": self.total_errors,
                "recoverable_errors": self.recoverable_errors,
            },

            # Overall
            "total_retries": self.total_retries,
        }

    def get_summary(self) -> str:
        """Get human-readable summary of metrics"""
        lines = [
            f"=== Performance Metrics for {self.session_id} ===",
            f"Duration: {self.total_duration_ms}ms",
            f"",
            f"Nodes executed: {len(self.node_latencies)}",
            f"Agents executed: {len(self.agent_execution_times)}",
            f"",
            f"LLM calls: {self.llm_call_count}",
            f"Total tokens: {self.llm_total_tokens:,}",
            f"Estimated cost: ${self.llm_cost_estimate:.4f}",
            f"",
            f"Cache hit rate: {self.cache_hit_rate:.1%}",
            f"Time saved by cache: {self.cache_time_saved:.1f}s",
            f"",
            f"Total errors: {self.total_errors} ({self.recoverable_errors} recoverable)",
            f"Total retries: {self.total_retries}",
            f"",
            f"Final quality score: {self.final_quality_score:.2f}" if self.final_quality_score else "",
        ]
        return "\n".join(lines)


class MetricsCollector:
    """Global metrics collector for workflow executions

    Maintains metrics for all active workflow sessions.
    """

    def __init__(self):
        self._metrics: Dict[str, PerformanceMetrics] = {}

    def start_session(self, session_id: str) -> PerformanceMetrics:
        """Start collecting metrics for a new session"""
        metrics = PerformanceMetrics(session_id=session_id)
        self._metrics[session_id] = metrics
        return metrics

    def get_session_metrics(self, session_id: str) -> Optional[PerformanceMetrics]:
        """Get metrics for a session"""
        return self._metrics.get(session_id)

    def finalize_session(self, session_id: str) -> Optional[PerformanceMetrics]:
        """Finalize and retrieve metrics for a session"""
        metrics = self._metrics.get(session_id)
        if metrics:
            metrics.finalize()
        return metrics

    def clear_session(self, session_id: str):
        """Remove metrics for a session"""
        self._metrics.pop(session_id, None)

    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """Get all active metrics"""
        return self._metrics.copy()


# Global metrics collector instance
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance"""
    return _metrics_collector
