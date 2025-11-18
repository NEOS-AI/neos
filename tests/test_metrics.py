"""
Unit tests for Enterprise Metrics Collector

Tests the Prometheus metrics collection functionality
"""

import pytest
import time
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from neos.observability.metrics import (
    EnterpriseMetricsCollector,
    get_metrics_collector,
)


@pytest.fixture
def metrics_collector():
    """Create a fresh metrics collector for each test"""
    from prometheus_client import CollectorRegistry
    registry = CollectorRegistry()
    return EnterpriseMetricsCollector(registry=registry)


@pytest.mark.unit
class TestEnterpriseMetricsCollector:
    """Test enterprise metrics collector"""

    def test_initialization(self, metrics_collector):
        """Test metrics collector initialization"""
        assert metrics_collector is not None
        assert metrics_collector.registry is not None
        assert hasattr(metrics_collector, 'http_requests_total')
        assert hasattr(metrics_collector, 'workflow_executions_total')
        assert hasattr(metrics_collector, 'llm_calls_total')

    def test_http_request_tracking(self, metrics_collector):
        """Test HTTP request metrics tracking"""
        # Increment request counter
        metrics_collector.http_requests_total.labels(
            method="GET",
            endpoint="/api/v1/health",
            status="200"
        ).inc()

        # Verify metric was recorded
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_http_requests_total' in metrics_data
        assert b'method="GET"' in metrics_data
        assert b'endpoint="/api/v1/health"' in metrics_data

    def test_request_duration_tracking(self, metrics_collector):
        """Test request duration histogram"""
        # Record request duration
        metrics_collector.http_request_duration_seconds.labels(
            method="POST",
            endpoint="/api/v1/query"
        ).observe(1.5)

        # Verify histogram metric
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_http_request_duration_seconds' in metrics_data

    def test_in_progress_requests(self, metrics_collector):
        """Test in-progress request gauge"""
        # Increment in-progress
        metrics_collector.http_requests_in_progress.labels(
            method="POST",
            endpoint="/api/v1/query"
        ).inc()

        assert metrics_collector.http_requests_in_progress.labels(
            method="POST",
            endpoint="/api/v1/query"
        )._value._value == 1

        # Decrement
        metrics_collector.http_requests_in_progress.labels(
            method="POST",
            endpoint="/api/v1/query"
        ).dec()

        assert metrics_collector.http_requests_in_progress.labels(
            method="POST",
            endpoint="/api/v1/query"
        )._value._value == 0

    @pytest.mark.asyncio
    async def test_track_request_decorator(self, metrics_collector):
        """Test request tracking decorator"""
        @metrics_collector.track_request("GET", "/test")
        async def test_endpoint():
            await asyncio.sleep(0.1)
            return {"status": "ok"}

        result = await test_endpoint()

        assert result == {"status": "ok"}

        # Verify metrics were recorded
        metrics_data = metrics_collector.export_metrics()
        assert b'/test' in metrics_data

    @pytest.mark.asyncio
    async def test_track_workflow_decorator(self, metrics_collector):
        """Test workflow tracking decorator"""
        @metrics_collector.track_workflow("test_workflow")
        async def test_workflow():
            await asyncio.sleep(0.05)
            return {
                "success": True,
                "quality_score": 0.85,
                "retry_count": 0
            }

        result = await test_workflow()

        assert result["success"] is True

        # Verify workflow metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_workflow_executions_total' in metrics_data
        assert b'test_workflow' in metrics_data

    @pytest.mark.asyncio
    async def test_track_agent_decorator(self, metrics_collector):
        """Test agent tracking decorator"""
        @metrics_collector.track_agent("deep_research")
        async def test_agent():
            await asyncio.sleep(0.05)
            return {"results": []}

        result = await test_agent()

        assert "results" in result

        # Verify agent metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_agent_executions_total' in metrics_data
        assert b'deep_research' in metrics_data

    @pytest.mark.asyncio
    async def test_track_agent_error(self, metrics_collector):
        """Test agent error tracking"""
        @metrics_collector.track_agent("test_agent")
        async def failing_agent():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await failing_agent()

        # Verify error was tracked
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_agent_errors_total' in metrics_data
        assert b'ValueError' in metrics_data

    def test_record_llm_call(self, metrics_collector):
        """Test LLM call recording"""
        metrics_collector.record_llm_call(
            provider="openai",
            model="gpt-4",
            duration=2.5,
            prompt_tokens=100,
            completion_tokens=50,
            status="success",
            cost_usd=0.015
        )

        # Verify all LLM metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_llm_calls_total' in metrics_data
        assert b'neos_llm_tokens_used' in metrics_data
        assert b'neos_llm_call_duration_seconds' in metrics_data
        assert b'neos_llm_cost_usd' in metrics_data
        assert b'provider="openai"' in metrics_data
        assert b'model="gpt-4"' in metrics_data

    def test_cache_metrics(self, metrics_collector):
        """Test cache hit/miss tracking"""
        # Record cache hits
        metrics_collector.record_cache_hit("workflow_response")
        metrics_collector.record_cache_hit("workflow_response")

        # Record cache misses
        metrics_collector.record_cache_miss("workflow_response")

        # Verify cache metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_cache_hits_total' in metrics_data
        assert b'neos_cache_misses_total' in metrics_data

    def test_database_connection_metrics(self, metrics_collector):
        """Test database connection metrics"""
        metrics_collector.set_db_connections(active=5, idle=3)

        assert metrics_collector.db_connections_active._value._value == 5
        assert metrics_collector.db_connections_idle._value._value == 3

        # Verify in export
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_db_connections_active' in metrics_data
        assert b'neos_db_connections_idle' in metrics_data

    def test_active_sessions_metric(self, metrics_collector):
        """Test active sessions gauge"""
        metrics_collector.set_active_sessions(42)

        assert metrics_collector.active_sessions._value._value == 42

        # Verify in export
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_active_sessions' in metrics_data

    def test_search_query_metrics(self, metrics_collector):
        """Test search query recording"""
        metrics_collector.record_search_query(
            search_type="knowledge_search",
            duration=1.2,
            results_count=15,
            status="success"
        )

        # Verify search metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_search_queries_total' in metrics_data
        assert b'neos_search_duration_seconds' in metrics_data
        assert b'neos_search_results_count' in metrics_data
        assert b'knowledge_search' in metrics_data

    def test_user_query_metrics(self, metrics_collector):
        """Test user query business metrics"""
        metrics_collector.record_user_query(
            user_type="premium",
            query_complexity="high"
        )

        # Verify user metrics
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_user_queries_total' in metrics_data
        assert b'user_type="premium"' in metrics_data
        assert b'query_complexity="high"' in metrics_data

    def test_export_metrics_format(self, metrics_collector):
        """Test metrics export format"""
        # Add some metrics
        metrics_collector.http_requests_total.labels(
            method="GET",
            endpoint="/test",
            status="200"
        ).inc()

        # Export metrics
        metrics_data = metrics_collector.export_metrics()

        # Verify it's bytes
        assert isinstance(metrics_data, bytes)

        # Verify Prometheus format
        decoded = metrics_data.decode('utf-8')
        assert '# HELP' in decoded or '# TYPE' in decoded

    def test_content_type(self, metrics_collector):
        """Test Prometheus content type"""
        content_type = metrics_collector.get_content_type()

        assert 'text/plain' in content_type or 'text' in content_type

    @pytest.mark.asyncio
    async def test_collect_system_metrics(self, metrics_collector):
        """Test system metrics collection"""
        # Mock psutil
        with patch('psutil.Process') as mock_process:
            mock_memory = MagicMock()
            mock_memory.rss = 100000000  # 100MB
            mock_memory.vms = 200000000  # 200MB

            mock_process_instance = MagicMock()
            mock_process_instance.memory_info.return_value = mock_memory
            mock_process.return_value = mock_process_instance

            # Run collection once (with timeout to prevent infinite loop)
            collection_task = asyncio.create_task(
                metrics_collector.collect_system_metrics()
            )

            # Let it run briefly
            await asyncio.sleep(0.1)

            # Cancel the task
            collection_task.cancel()

            try:
                await collection_task
            except asyncio.CancelledError:
                pass

            # Verify memory metrics were set
            metrics_data = metrics_collector.export_metrics()
            assert b'neos_memory_usage_bytes' in metrics_data


@pytest.mark.unit
class TestMetricsGlobalInstance:
    """Test global metrics collector instance"""

    def test_get_metrics_collector_singleton(self):
        """Test that get_metrics_collector returns singleton"""
        # Get collector twice
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()

        # Should be same instance
        assert collector1 is collector2

    def test_convenience_aliases(self):
        """Test convenience function aliases"""
        from neos.observability.metrics import metrics, track_request, track_workflow, track_agent

        assert metrics is not None
        assert callable(track_request)
        assert callable(track_workflow)
        assert callable(track_agent)


@pytest.mark.unit
class TestMetricsDecorators:
    """Test metrics decorator functionality"""

    @pytest.mark.asyncio
    async def test_request_decorator_error_handling(self, metrics_collector):
        """Test request decorator handles errors properly"""
        @metrics_collector.track_request("POST", "/error")
        async def failing_request():
            raise Exception("Test error")

        with pytest.raises(Exception):
            await failing_request()

        # Verify error status was recorded
        metrics_data = metrics_collector.export_metrics()
        assert b'status="500"' in metrics_data

    @pytest.mark.asyncio
    async def test_workflow_decorator_with_retries(self, metrics_collector):
        """Test workflow decorator tracks retries"""
        @metrics_collector.track_workflow("retry_workflow")
        async def workflow_with_retries():
            return {
                "success": True,
                "quality_score": 0.75,
                "retry_count": 2
            }

        await workflow_with_retries()

        # Verify retry count was tracked
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_workflow_retry_count' in metrics_data

    @pytest.mark.asyncio
    async def test_workflow_decorator_without_quality(self, metrics_collector):
        """Test workflow decorator when quality score not provided"""
        @metrics_collector.track_workflow("simple_workflow")
        async def simple_workflow():
            return {"success": True}

        result = await simple_workflow()

        assert result["success"] is True
        # Should not raise error even without quality_score

    @pytest.mark.asyncio
    async def test_agent_decorator_timing(self, metrics_collector):
        """Test agent decorator records accurate timing"""
        @metrics_collector.track_agent("timed_agent")
        async def timed_agent():
            await asyncio.sleep(0.1)
            return {"done": True}

        start = time.time()
        await timed_agent()
        duration = time.time() - start

        # Duration should be at least 0.1 seconds
        assert duration >= 0.1

        # Verify duration histogram has data
        metrics_data = metrics_collector.export_metrics()
        assert b'neos_agent_duration_seconds' in metrics_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
