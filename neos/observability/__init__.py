"""
NEOS Observability Module

Phoenix-based observability for LangGraph and CrewAI multi-agent workflows.
Provides comprehensive tracing, monitoring, and analytics for AI agent operations.
"""

from .core import ObservabilityManager
from .decorators import trace_agent, trace_workflow, trace_llm_call
from .phoenix_client import PhoenixClient
from .collectors import MetricsCollector, TraceCollector
from .middleware import ObservabilityMiddleware

__all__ = [
    "ObservabilityManager",
    "PhoenixClient",
    "MetricsCollector",
    "TraceCollector",
    "ObservabilityMiddleware",
    "trace_agent",
    "trace_workflow",
    "trace_llm_call"
]