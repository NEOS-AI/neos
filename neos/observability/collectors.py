"""
Data collectors for NEOS observability.
Handles metrics collection and trace storage.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
import json
from dataclasses import dataclass, asdict

from ..config.settings import Settings


logger = logging.getLogger(__name__)


@dataclass
class WorkflowMetrics:
    """Workflow performance metrics."""
    workflow_id: str
    workflow_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    status: str = "running"
    agent_count: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    error_count: int = 0
    quality_score: Optional[float] = None


@dataclass
class AgentMetrics:
    """Agent execution metrics."""
    agent_id: str
    agent_type: str
    execution_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    status: str = "running"
    task: str = ""
    llm_calls: int = 0
    tokens_used: int = 0
    cost: float = 0.0
    success: bool = False
    error_message: Optional[str] = None


@dataclass
class LLMMetrics:
    """LLM API call metrics."""
    timestamp: datetime
    provider: str
    model: str
    prompt_length: int
    response_length: int
    tokens_used: Optional[int] = None
    cost: Optional[float] = None
    latency: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None


class MetricsCollector:
    """
    Collects and aggregates performance metrics for NEOS system.

    Tracks:
    - Workflow execution metrics
    - Agent performance metrics
    - LLM usage and cost metrics
    - System performance indicators
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # Metrics storage
        self.workflow_metrics: Dict[str, WorkflowMetrics] = {}
        self.agent_metrics: Dict[str, AgentMetrics] = {}
        self.llm_metrics: deque = deque(maxlen=10000)  # Keep last 10k LLM calls

        # Aggregated metrics
        self.hourly_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'workflows': 0,
            'agents': 0,
            'llm_calls': 0,
            'total_tokens': 0,
            'total_cost': 0.0,
            'errors': 0
        })

        self.daily_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'workflows': 0,
            'agents': 0,
            'llm_calls': 0,
            'total_tokens': 0,
            'total_cost': 0.0,
            'errors': 0
        })

        # Real-time metrics
        self.current_metrics = {
            'active_workflows': 0,
            'active_agents': 0,
            'total_workflows_today': 0,
            'total_agents_today': 0,
            'avg_workflow_duration': 0.0,
            'avg_agent_duration': 0.0,
            'success_rate': 1.0,
            'cost_today': 0.0
        }

        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize metrics collector."""
        logger.info("Initializing metrics collector...")

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_old_metrics())

        logger.info("Metrics collector initialized")

    async def record_workflow_start(self, session_data: Dict[str, Any]) -> None:
        """Record workflow start metrics."""
        workflow_id = session_data['workflow_id']
        metrics = WorkflowMetrics(
            workflow_id=workflow_id,
            workflow_type=session_data['workflow_type'],
            start_time=session_data['start_time'],
            status='running'
        )

        self.workflow_metrics[session_data['session_id']] = metrics
        self.current_metrics['active_workflows'] += 1

        # Update daily stats
        today = datetime.now().date().isoformat()
        self.daily_stats[today]['workflows'] += 1
        self.current_metrics['total_workflows_today'] = self.daily_stats[today]['workflows']

        logger.debug(f"Recorded workflow start: {workflow_id}")

    async def record_workflow_end(self, session_data: Dict[str, Any]) -> None:
        """Record workflow completion metrics."""
        session_id = session_data['session_id']

        if session_id not in self.workflow_metrics:
            logger.warning(f"Workflow metrics not found: {session_id}")
            return

        metrics = self.workflow_metrics[session_id]
        metrics.end_time = session_data['end_time']
        metrics.duration = session_data['duration']
        metrics.status = session_data['status']
        metrics.agent_count = len(session_data.get('agents', []))

        if session_data.get('error'):
            metrics.error_count = 1
            today = datetime.now().date().isoformat()
            self.daily_stats[today]['errors'] += 1

        self.current_metrics['active_workflows'] -= 1

        # Update average duration
        await self._update_average_workflow_duration()

        # Update success rate
        await self._update_success_rate()

        logger.debug(f"Recorded workflow end: {session_data['workflow_id']}")

    async def record_agent_start(self, execution_data: Dict[str, Any]) -> None:
        """Record agent execution start metrics."""
        execution_id = execution_data['execution_id']
        metrics = AgentMetrics(
            agent_id=execution_data['agent_id'],
            agent_type=execution_data['agent_type'],
            execution_id=execution_id,
            start_time=execution_data['start_time'],
            task=execution_data['task'],
            status='running'
        )

        self.agent_metrics[execution_id] = metrics
        self.current_metrics['active_agents'] += 1

        # Update daily stats
        today = datetime.now().date().isoformat()
        self.daily_stats[today]['agents'] += 1
        self.current_metrics['total_agents_today'] = self.daily_stats[today]['agents']

        logger.debug(f"Recorded agent start: {execution_data['agent_id']}")

    async def record_agent_end(self, execution_data: Dict[str, Any]) -> None:
        """Record agent execution completion metrics."""
        execution_id = execution_data['execution_id']

        if execution_id not in self.agent_metrics:
            logger.warning(f"Agent metrics not found: {execution_id}")
            return

        metrics = self.agent_metrics[execution_id]
        metrics.end_time = execution_data['end_time']
        metrics.duration = execution_data['duration']
        metrics.status = execution_data['status']
        metrics.success = execution_data['status'] == 'completed'
        metrics.error_message = execution_data.get('error')
        metrics.llm_calls = len(execution_data.get('llm_calls', []))

        # Calculate LLM metrics
        for llm_call in execution_data.get('llm_calls', []):
            if llm_call.get('tokens_used'):
                metrics.tokens_used += llm_call['tokens_used']
            if llm_call.get('cost'):
                metrics.cost += llm_call['cost']

        self.current_metrics['active_agents'] -= 1

        # Update average duration
        await self._update_average_agent_duration()

        logger.debug(f"Recorded agent end: {execution_data['agent_id']}")

    async def record_llm_call(self, call_data: Dict[str, Any]) -> None:
        """Record LLM API call metrics."""
        metrics = LLMMetrics(
            timestamp=call_data['timestamp'],
            provider=call_data['provider'],
            model=call_data['model'],
            prompt_length=call_data['prompt_length'],
            response_length=call_data['response_length'],
            tokens_used=call_data.get('tokens_used'),
            cost=call_data.get('cost')
        )

        self.llm_metrics.append(metrics)

        # Update daily stats
        today = datetime.now().date().isoformat()
        self.daily_stats[today]['llm_calls'] += 1

        if metrics.tokens_used:
            self.daily_stats[today]['total_tokens'] += metrics.tokens_used

        if metrics.cost:
            self.daily_stats[today]['total_cost'] += metrics.cost
            self.current_metrics['cost_today'] = self.daily_stats[today]['total_cost']

        # Update hourly stats
        hour = call_data['timestamp'].strftime('%Y-%m-%d-%H')
        self.hourly_stats[hour]['llm_calls'] += 1

        if metrics.tokens_used:
            self.hourly_stats[hour]['total_tokens'] += metrics.tokens_used

        if metrics.cost:
            self.hourly_stats[hour]['total_cost'] += metrics.cost

        logger.debug(f"Recorded LLM call: {call_data['provider']}/{call_data['model']}")

    async def get_workflow_metrics(self, workflow_id: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get workflow performance metrics."""
        filtered_metrics = []

        for metrics in self.workflow_metrics.values():
            # Filter by workflow_id
            if workflow_id and metrics.workflow_id != workflow_id:
                continue

            # Filter by time range
            if start_time and metrics.start_time < start_time:
                continue

            if end_time and metrics.end_time and metrics.end_time > end_time:
                continue

            filtered_metrics.append(asdict(metrics))

        # Calculate aggregated stats
        total_workflows = len(filtered_metrics)
        completed_workflows = len([m for m in filtered_metrics if m['status'] == 'completed'])
        failed_workflows = len([m for m in filtered_metrics if m['status'] == 'error'])

        durations = [m['duration'] for m in filtered_metrics if m['duration']]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            'total_workflows': total_workflows,
            'completed_workflows': completed_workflows,
            'failed_workflows': failed_workflows,
            'success_rate': completed_workflows / total_workflows if total_workflows > 0 else 0,
            'average_duration': avg_duration,
            'workflows': filtered_metrics
        }

    async def get_agent_metrics(self, agent_id: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get agent performance metrics."""
        filtered_metrics = []

        for metrics in self.agent_metrics.values():
            # Filter by agent_id
            if agent_id and metrics.agent_id != agent_id:
                continue

            # Filter by time range
            if start_time and metrics.start_time < start_time:
                continue

            if end_time and metrics.end_time and metrics.end_time > end_time:
                continue

            filtered_metrics.append(asdict(metrics))

        # Calculate aggregated stats
        total_executions = len(filtered_metrics)
        successful_executions = len([m for m in filtered_metrics if m['success']])
        failed_executions = total_executions - successful_executions

        durations = [m['duration'] for m in filtered_metrics if m['duration']]
        avg_duration = sum(durations) / len(durations) if durations else 0

        total_tokens = sum(m['tokens_used'] for m in filtered_metrics)
        total_cost = sum(m['cost'] for m in filtered_metrics)

        return {
            'total_executions': total_executions,
            'successful_executions': successful_executions,
            'failed_executions': failed_executions,
            'success_rate': successful_executions / total_executions if total_executions > 0 else 0,
            'average_duration': avg_duration,
            'total_tokens': total_tokens,
            'total_cost': total_cost,
            'agents': filtered_metrics
        }

    async def get_llm_metrics(self, provider: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Get LLM usage metrics."""
        filtered_metrics = []

        for metrics in self.llm_metrics:
            # Filter by provider
            if provider and metrics.provider != provider:
                continue

            # Filter by time range
            if start_time and metrics.timestamp < start_time:
                continue

            if end_time and metrics.timestamp > end_time:
                continue

            filtered_metrics.append(asdict(metrics))

        # Calculate aggregated stats
        total_calls = len(filtered_metrics)
        total_tokens = sum(m['tokens_used'] for m in filtered_metrics if m['tokens_used'])
        total_cost = sum(m['cost'] for m in filtered_metrics if m['cost'])

        # Group by provider and model
        provider_stats = defaultdict(lambda: {'calls': 0, 'tokens': 0, 'cost': 0.0})
        model_stats = defaultdict(lambda: {'calls': 0, 'tokens': 0, 'cost': 0.0})

        for metrics in filtered_metrics:
            provider_stats[metrics['provider']]['calls'] += 1
            model_stats[metrics['model']]['calls'] += 1

            if metrics['tokens_used']:
                provider_stats[metrics['provider']]['tokens'] += metrics['tokens_used']
                model_stats[metrics['model']]['tokens'] += metrics['tokens_used']

            if metrics['cost']:
                provider_stats[metrics['provider']]['cost'] += metrics['cost']
                model_stats[metrics['model']]['cost'] += metrics['cost']

        return {
            'total_calls': total_calls,
            'total_tokens': total_tokens,
            'total_cost': total_cost,
            'provider_stats': dict(provider_stats),
            'model_stats': dict(model_stats),
            'calls': filtered_metrics
        }

    async def get_real_time_metrics(self) -> Dict[str, Any]:
        """Get current real-time metrics."""
        return self.current_metrics.copy()

    async def get_daily_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get daily statistics for the last N days."""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days - 1)

        daily_data = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.isoformat()
            stats = self.daily_stats.get(date_str, {
                'workflows': 0,
                'agents': 0,
                'llm_calls': 0,
                'total_tokens': 0,
                'total_cost': 0.0,
                'errors': 0
            })
            stats['date'] = date_str
            daily_data.append(stats)
            current_date += timedelta(days=1)

        return {
            'period_days': days,
            'daily_stats': daily_data
        }

    async def _update_average_workflow_duration(self) -> None:
        """Update average workflow duration."""
        completed_workflows = [
            m for m in self.workflow_metrics.values()
            if m.duration is not None
        ]

        if completed_workflows:
            total_duration = sum(m.duration for m in completed_workflows)
            self.current_metrics['avg_workflow_duration'] = total_duration / len(completed_workflows)

    async def _update_average_agent_duration(self) -> None:
        """Update average agent duration."""
        completed_agents = [
            m for m in self.agent_metrics.values()
            if m.duration is not None
        ]

        if completed_agents:
            total_duration = sum(m.duration for m in completed_agents)
            self.current_metrics['avg_agent_duration'] = total_duration / len(completed_agents)

    async def _update_success_rate(self) -> None:
        """Update overall success rate."""
        today = datetime.now().date().isoformat()
        total_workflows = self.daily_stats[today]['workflows']
        errors = self.daily_stats[today]['errors']

        if total_workflows > 0:
            self.current_metrics['success_rate'] = 1.0 - (errors / total_workflows)

    async def _cleanup_old_metrics(self) -> None:
        """Cleanup old metrics data periodically."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour

                cutoff_time = datetime.now() - timedelta(days=30)

                # Cleanup old workflow metrics
                old_sessions = [
                    session_id for session_id, metrics in self.workflow_metrics.items()
                    if metrics.start_time < cutoff_time
                ]

                for session_id in old_sessions:
                    del self.workflow_metrics[session_id]

                # Cleanup old agent metrics
                old_executions = [
                    execution_id for execution_id, metrics in self.agent_metrics.items()
                    if metrics.start_time < cutoff_time
                ]

                for execution_id in old_executions:
                    del self.agent_metrics[execution_id]

                # Cleanup old hourly stats
                cutoff_hour = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d-%H')
                old_hours = [
                    hour for hour in self.hourly_stats.keys()
                    if hour < cutoff_hour
                ]

                for hour in old_hours:
                    del self.hourly_stats[hour]

                logger.debug("Completed metrics cleanup")

            except Exception as e:
                logger.error(f"Error during metrics cleanup: {e}")

    async def shutdown(self) -> None:
        """Shutdown metrics collector."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Metrics collector shutdown completed")


class TraceCollector:
    """
    Collects and stores detailed trace information for analysis.

    Stores:
    - Workflow execution traces
    - Agent execution traces
    - LLM interaction traces
    - Error traces and stack traces
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # Trace storage
        self.workflow_traces: Dict[str, Dict[str, Any]] = {}
        self.agent_traces: Dict[str, Dict[str, Any]] = {}
        self.error_traces: List[Dict[str, Any]] = []

        # Trace retention
        self.max_traces = getattr(settings, 'MAX_TRACES', 1000)
        self.trace_retention_days = getattr(settings, 'TRACE_RETENTION_DAYS', 30)

    async def initialize(self) -> None:
        """Initialize trace collector."""
        logger.info("Initializing trace collector...")
        logger.info("Trace collector initialized")

    async def store_workflow_trace(self, session_data: Dict[str, Any]) -> None:
        """Store workflow execution trace."""
        trace_id = session_data['session_id']

        trace_data = {
            'trace_id': trace_id,
            'workflow_id': session_data['workflow_id'],
            'workflow_type': session_data['workflow_type'],
            'start_time': session_data['start_time'].isoformat(),
            'end_time': session_data.get('end_time', datetime.now()).isoformat(),
            'duration': session_data.get('duration'),
            'status': session_data.get('status'),
            'metadata': session_data.get('metadata', {}),
            'agents': session_data.get('agents', []),
            'result': session_data.get('result'),
            'error': session_data.get('error')
        }

        self.workflow_traces[trace_id] = trace_data

        # Store error trace if failed
        if session_data.get('error'):
            await self._store_error_trace('workflow', trace_id, session_data['error'])

        # Cleanup old traces
        await self._cleanup_traces()

        logger.debug(f"Stored workflow trace: {trace_id}")

    async def store_agent_trace(self, execution_data: Dict[str, Any]) -> None:
        """Store agent execution trace."""
        trace_id = execution_data['execution_id']

        trace_data = {
            'trace_id': trace_id,
            'agent_id': execution_data['agent_id'],
            'agent_type': execution_data['agent_type'],
            'task': execution_data['task'],
            'workflow_session_id': execution_data.get('workflow_session_id'),
            'start_time': execution_data['start_time'].isoformat(),
            'end_time': execution_data.get('end_time', datetime.now()).isoformat(),
            'duration': execution_data.get('duration'),
            'status': execution_data.get('status'),
            'llm_calls': execution_data.get('llm_calls', []),
            'result': execution_data.get('result'),
            'error': execution_data.get('error')
        }

        self.agent_traces[trace_id] = trace_data

        # Store error trace if failed
        if execution_data.get('error'):
            await self._store_error_trace('agent', trace_id, execution_data['error'])

        logger.debug(f"Stored agent trace: {trace_id}")

    async def _store_error_trace(self, trace_type: str, trace_id: str, error: str) -> None:
        """Store error trace information."""
        error_trace = {
            'timestamp': datetime.now().isoformat(),
            'trace_type': trace_type,
            'trace_id': trace_id,
            'error_message': error,
            'error_type': type(error).__name__ if isinstance(error, Exception) else 'UnknownError'
        }

        self.error_traces.append(error_trace)

        # Keep only recent errors
        if len(self.error_traces) > 1000:
            self.error_traces = self.error_traces[-1000:]

        logger.debug(f"Stored error trace: {trace_type}/{trace_id}")

    async def get_workflow_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow trace by ID."""
        return self.workflow_traces.get(trace_id)

    async def get_agent_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get agent trace by ID."""
        return self.agent_traces.get(trace_id)

    async def get_error_traces(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent error traces."""
        return self.error_traces[-limit:] if limit else self.error_traces

    async def search_traces(self, query: str, trace_type: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Search traces by query and filters."""
        results = []

        # Search workflow traces
        if not trace_type or trace_type == 'workflow':
            for trace in self.workflow_traces.values():
                if self._match_trace(trace, query, start_time, end_time):
                    results.append({**trace, 'trace_type': 'workflow'})

        # Search agent traces
        if not trace_type or trace_type == 'agent':
            for trace in self.agent_traces.values():
                if self._match_trace(trace, query, start_time, end_time):
                    results.append({**trace, 'trace_type': 'agent'})

        # Sort by start time (newest first)
        results.sort(key=lambda x: x.get('start_time', ''), reverse=True)

        return results

    def _match_trace(self, trace: Dict[str, Any], query: str, start_time: Optional[datetime], end_time: Optional[datetime]) -> bool:
        """Check if trace matches search criteria."""
        # Time range filter
        if start_time:
            trace_start = datetime.fromisoformat(trace['start_time'])
            if trace_start < start_time:
                return False

        if end_time:
            trace_start = datetime.fromisoformat(trace['start_time'])
            if trace_start > end_time:
                return False

        # Text search
        if query:
            query_lower = query.lower()
            searchable_text = json.dumps(trace).lower()
            if query_lower not in searchable_text:
                return False

        return True

    async def _cleanup_traces(self) -> None:
        """Cleanup old traces."""
        cutoff_time = datetime.now() - timedelta(days=self.trace_retention_days)
        cutoff_str = cutoff_time.isoformat()

        # Cleanup workflow traces
        old_workflow_traces = [
            trace_id for trace_id, trace in self.workflow_traces.items()
            if trace['start_time'] < cutoff_str
        ]

        for trace_id in old_workflow_traces:
            del self.workflow_traces[trace_id]

        # Cleanup agent traces
        old_agent_traces = [
            trace_id for trace_id, trace in self.agent_traces.items()
            if trace['start_time'] < cutoff_str
        ]

        for trace_id in old_agent_traces:
            del self.agent_traces[trace_id]

        # Limit total traces
        if len(self.workflow_traces) > self.max_traces:
            # Keep most recent traces
            sorted_traces = sorted(
                self.workflow_traces.items(),
                key=lambda x: x[1]['start_time'],
                reverse=True
            )
            self.workflow_traces = dict(sorted_traces[:self.max_traces])

        if len(self.agent_traces) > self.max_traces:
            # Keep most recent traces
            sorted_traces = sorted(
                self.agent_traces.items(),
                key=lambda x: x[1]['start_time'],
                reverse=True
            )
            self.agent_traces = dict(sorted_traces[:self.max_traces])

    async def shutdown(self) -> None:
        """Shutdown trace collector."""
        logger.info("Trace collector shutdown completed")