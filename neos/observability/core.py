"""
Core observability manager for NEOS multi-agent system.
Orchestrates Phoenix tracing, metrics collection, and monitoring.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from datetime import datetime
import uuid

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import resources
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..config.settings import Settings
from .phoenix_client import PhoenixClient
from .collectors import MetricsCollector, TraceCollector


logger = logging.getLogger(__name__)


class ObservabilityManager:
    """
    Central manager for observability in NEOS multi-agent system.

    Handles:
    - Phoenix tracing for LangGraph workflows
    - CrewAI agent monitoring
    - LLM call tracking
    - Performance metrics collection
    - Error tracking and analysis
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session_id = str(uuid.uuid4())

        # Core components
        self.phoenix_client: Optional[PhoenixClient] = None
        self.metrics_collector: Optional[MetricsCollector] = None
        self.trace_collector: Optional[TraceCollector] = None

        # OpenTelemetry setup
        self.tracer_provider: Optional[TracerProvider] = None
        self.tracer = None

        # State tracking
        self._active_traces: Dict[str, Any] = {}
        self._workflow_sessions: Dict[str, Dict[str, Any]] = {}
        self._agent_sessions: Dict[str, Dict[str, Any]] = {}

        self._initialized = False
        logger.info(f"ObservabilityManager created with session ID: {self.session_id}")

    async def initialize(self) -> None:
        """Initialize all observability components."""
        if self._initialized:
            logger.warning("ObservabilityManager already initialized")
            return

        try:
            logger.info("Initializing observability components...")

            # Initialize Phoenix client
            await self._setup_phoenix()

            # Initialize collectors
            await self._setup_collectors()

            # Setup OpenTelemetry
            await self._setup_opentelemetry()

            self._initialized = True
            logger.info("Observability initialization completed successfully")

        except Exception as e:
            logger.error(f"Failed to initialize observability: {e}")
            raise

    async def _setup_phoenix(self) -> None:
        """Setup Phoenix tracing."""
        phoenix_config = {
            'project_name': 'neos-multi-agent',
            'host': getattr(self.settings, 'PHOENIX_HOST', 'localhost'),
            'port': getattr(self.settings, 'PHOENIX_PORT', 6006),
            'collector_endpoint': getattr(self.settings, 'PHOENIX_COLLECTOR_ENDPOINT', None)
        }

        self.phoenix_client = PhoenixClient(phoenix_config)
        await self.phoenix_client.initialize()

        logger.info("Phoenix tracing initialized")

    async def _setup_collectors(self) -> None:
        """Setup metrics and trace collectors."""
        self.metrics_collector = MetricsCollector(self.settings)
        self.trace_collector = TraceCollector(self.settings)

        await asyncio.gather(
            self.metrics_collector.initialize(),
            self.trace_collector.initialize()
        )

        logger.info("Collectors initialized")

    async def _setup_opentelemetry(self) -> None:
        """Setup OpenTelemetry tracing."""
        # Create resource
        resource = resources.Resource.create({
            "service.name": "neos-ai-system",
            "service.version": "1.0.0",
            "deployment.environment": getattr(self.settings, 'ENVIRONMENT', 'development')
        })

        # Create tracer provider
        self.tracer_provider = TracerProvider(resource=resource)

        # Setup OTLP exporter if configured
        if self.phoenix_client and self.phoenix_client.collector_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=self.phoenix_client.collector_endpoint)
            span_processor = BatchSpanProcessor(otlp_exporter)
            self.tracer_provider.add_span_processor(span_processor)

        # Set global tracer provider
        trace.set_tracer_provider(self.tracer_provider)
        self.tracer = trace.get_tracer(__name__)

        logger.info("OpenTelemetry setup completed")

    async def start_workflow_session(self, workflow_id: str, workflow_type: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Start tracking a new workflow session."""
        session_id = f"{workflow_id}_{datetime.now().isoformat()}"

        session_data = {
            'workflow_id': workflow_id,
            'workflow_type': workflow_type,
            'session_id': session_id,
            'start_time': datetime.now(),
            'metadata': metadata or {},
            'agents': [],
            'status': 'running'
        }

        self._workflow_sessions[session_id] = session_data

        # Start Phoenix tracing
        if self.phoenix_client:
            await self.phoenix_client.start_session(session_id, 'workflow', session_data)

        # Collect initial metrics
        if self.metrics_collector:
            await self.metrics_collector.record_workflow_start(session_data)

        logger.info(f"Started workflow session: {session_id}")
        return session_id

    async def end_workflow_session(self, session_id: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """End a workflow session."""
        if session_id not in self._workflow_sessions:
            logger.warning(f"Workflow session not found: {session_id}")
            return

        session_data = self._workflow_sessions[session_id]
        session_data['end_time'] = datetime.now()
        session_data['duration'] = (session_data['end_time'] - session_data['start_time']).total_seconds()
        session_data['result'] = result
        session_data['error'] = error
        session_data['status'] = 'error' if error else 'completed'

        # End Phoenix tracing
        if self.phoenix_client:
            await self.phoenix_client.end_session(session_id, session_data)

        # Collect final metrics
        if self.metrics_collector:
            await self.metrics_collector.record_workflow_end(session_data)

        # Store trace
        if self.trace_collector:
            await self.trace_collector.store_workflow_trace(session_data)

        logger.info(f"Ended workflow session: {session_id} (duration: {session_data['duration']:.2f}s)")

    async def start_agent_execution(self, agent_id: str, agent_type: str, task: str, workflow_session_id: Optional[str] = None) -> str:
        """Start tracking an agent execution."""
        execution_id = f"{agent_id}_{datetime.now().isoformat()}"

        execution_data = {
            'agent_id': agent_id,
            'agent_type': agent_type,
            'execution_id': execution_id,
            'task': task,
            'workflow_session_id': workflow_session_id,
            'start_time': datetime.now(),
            'llm_calls': [],
            'status': 'running'
        }

        self._agent_sessions[execution_id] = execution_data

        # Add to workflow session if provided
        if workflow_session_id and workflow_session_id in self._workflow_sessions:
            self._workflow_sessions[workflow_session_id]['agents'].append(execution_id)

        # Start Phoenix tracing
        if self.phoenix_client:
            await self.phoenix_client.start_agent_trace(execution_id, execution_data)

        # Collect metrics
        if self.metrics_collector:
            await self.metrics_collector.record_agent_start(execution_data)

        logger.info(f"Started agent execution: {execution_id}")
        return execution_id

    async def end_agent_execution(self, execution_id: str, result: Optional[Any] = None, error: Optional[str] = None) -> None:
        """End an agent execution."""
        if execution_id not in self._agent_sessions:
            logger.warning(f"Agent execution not found: {execution_id}")
            return

        execution_data = self._agent_sessions[execution_id]
        execution_data['end_time'] = datetime.now()
        execution_data['duration'] = (execution_data['end_time'] - execution_data['start_time']).total_seconds()
        execution_data['result'] = result
        execution_data['error'] = error
        execution_data['status'] = 'error' if error else 'completed'

        # End Phoenix tracing
        if self.phoenix_client:
            await self.phoenix_client.end_agent_trace(execution_id, execution_data)

        # Collect metrics
        if self.metrics_collector:
            await self.metrics_collector.record_agent_end(execution_data)

        # Store trace
        if self.trace_collector:
            await self.trace_collector.store_agent_trace(execution_data)

        logger.info(f"Ended agent execution: {execution_id} (duration: {execution_data['duration']:.2f}s)")

    async def track_llm_call(self, execution_id: str, provider: str, model: str, prompt: str, response: str, tokens_used: Optional[int] = None, cost: Optional[float] = None) -> None:
        """Track an LLM API call."""
        call_data = {
            'timestamp': datetime.now(),
            'provider': provider,
            'model': model,
            'prompt_length': len(prompt),
            'response_length': len(response),
            'tokens_used': tokens_used,
            'cost': cost
        }

        # Add to agent session
        if execution_id in self._agent_sessions:
            self._agent_sessions[execution_id]['llm_calls'].append(call_data)

        # Track in Phoenix
        if self.phoenix_client:
            await self.phoenix_client.track_llm_call(execution_id, call_data, prompt, response)

        # Collect metrics
        if self.metrics_collector:
            await self.metrics_collector.record_llm_call(call_data)

        logger.debug(f"Tracked LLM call for execution: {execution_id}")

    @asynccontextmanager
    async def trace_workflow(self, workflow_id: str, workflow_type: str, metadata: Optional[Dict[str, Any]] = None):
        """Context manager for tracing workflow execution."""
        session_id = await self.start_workflow_session(workflow_id, workflow_type, metadata)
        try:
            yield session_id
        except Exception as e:
            await self.end_workflow_session(session_id, error=str(e))
            raise
        else:
            await self.end_workflow_session(session_id)

    @asynccontextmanager
    async def trace_agent(self, agent_id: str, agent_type: str, task: str, workflow_session_id: Optional[str] = None):
        """Context manager for tracing agent execution."""
        execution_id = await self.start_agent_execution(agent_id, agent_type, task, workflow_session_id)
        try:
            yield execution_id
        except Exception as e:
            await self.end_agent_execution(execution_id, error=str(e))
            raise
        else:
            await self.end_agent_execution(execution_id)

    async def get_workflow_metrics(self, workflow_id: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get workflow performance metrics."""
        if not self.metrics_collector:
            return {}

        return await self.metrics_collector.get_workflow_metrics(workflow_id, start_time, end_time)

    async def get_agent_metrics(self, agent_id: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get agent performance metrics."""
        if not self.metrics_collector:
            return {}

        return await self.metrics_collector.get_agent_metrics(agent_id, start_time, end_time)

    async def get_llm_metrics(self, provider: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get LLM usage metrics."""
        if not self.metrics_collector:
            return {}

        return await self.metrics_collector.get_llm_metrics(provider, start_time, end_time)

    async def get_real_time_metrics(self) -> Dict[str, Any]:
        """Get real-time metrics."""
        if not self.metrics_collector:
            return {}

        return await self.metrics_collector.get_real_time_metrics()

    async def get_daily_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get daily statistics."""
        if not self.metrics_collector:
            return {}

        return await self.metrics_collector.get_daily_stats(days)

    async def shutdown(self) -> None:
        """Shutdown observability components."""
        logger.info("Shutting down observability components...")

        # Shutdown collectors
        if self.metrics_collector:
            await self.metrics_collector.shutdown()

        if self.trace_collector:
            await self.trace_collector.shutdown()

        # Shutdown Phoenix client
        if self.phoenix_client:
            await self.phoenix_client.shutdown()

        # Shutdown tracer provider
        if self.tracer_provider:
            self.tracer_provider.shutdown()

        self._initialized = False
        logger.info("Observability shutdown completed")