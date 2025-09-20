"""
Integration helpers for NEOS observability.
Easy integration points for existing NEOS components.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Type, Callable
from functools import wraps

from ..config.settings import Settings
from .core import ObservabilityManager
from .middleware import ObservabilityMiddleware, LangGraphObservabilityHook, CrewAIObservabilityHook
from .decorators import create_observability_decorators


logger = logging.getLogger(__name__)


class NEOSObservabilityIntegration:
    """
    Main integration class for NEOS observability.

    Provides easy setup and integration with existing NEOS components.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.obs_manager: Optional[ObservabilityManager] = None
        self.decorators = None
        self.middleware = None
        self.langgraph_hook = None
        self.crewai_hook = None

        self._initialized = False

    async def initialize(self) -> None:
        """Initialize observability integration."""
        if self._initialized:
            logger.warning("Observability integration already initialized")
            return

        if not self.settings.OBSERVABILITY_ENABLED:
            logger.info("Observability is disabled in settings")
            return

        try:
            logger.info("Initializing NEOS observability integration...")

            # Initialize observability manager
            self.obs_manager = ObservabilityManager(self.settings)
            await self.obs_manager.initialize()

            # Create components
            self.decorators = create_observability_decorators(self.obs_manager)
            self.langgraph_hook = LangGraphObservabilityHook(self.obs_manager)
            self.crewai_hook = CrewAIObservabilityHook(self.obs_manager)

            self._initialized = True
            logger.info("NEOS observability integration initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize observability integration: {e}")
            raise

    async def shutdown(self) -> None:
        """Shutdown observability integration."""
        if not self._initialized:
            return

        try:
            logger.info("Shutting down NEOS observability integration...")

            if self.obs_manager:
                await self.obs_manager.shutdown()

            self._initialized = False
            logger.info("NEOS observability integration shutdown completed")

        except Exception as e:
            logger.error(f"Error during observability shutdown: {e}")

    def get_middleware(self, **kwargs) -> ObservabilityMiddleware:
        """Get FastAPI middleware for observability."""
        if not self._initialized or not self.obs_manager:
            raise RuntimeError("Observability integration not initialized")

        return ObservabilityMiddleware(
            observability_manager=self.obs_manager,
            **kwargs
        )

    def trace_workflow(self, **kwargs):
        """Get workflow decorator."""
        if not self._initialized or not self.decorators:
            return lambda func: func  # No-op decorator

        return self.decorators.workflow(**kwargs)

    def trace_agent(self, **kwargs):
        """Get agent decorator."""
        if not self._initialized or not self.decorators:
            return lambda func: func  # No-op decorator

        return self.decorators.agent(**kwargs)

    def trace_llm_call(self, **kwargs):
        """Get LLM call decorator."""
        if not self._initialized or not self.decorators:
            return lambda func: func  # No-op decorator

        return self.decorators.llm_call(**kwargs)

    async def track_workflow_manually(self, workflow_id: str, workflow_type: str, metadata: Optional[Dict[str, Any]] = None):
        """Manually track workflow (context manager)."""
        if not self._initialized or not self.obs_manager:
            # Return a no-op context manager
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def noop():
                yield None

            return noop()

        return self.obs_manager.trace_workflow(workflow_id, workflow_type, metadata)

    async def track_agent_manually(self, agent_id: str, agent_type: str, task: str, workflow_session_id: Optional[str] = None):
        """Manually track agent execution (context manager)."""
        if not self._initialized or not self.obs_manager:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def noop():
                yield None

            return noop()

        return self.obs_manager.trace_agent(agent_id, agent_type, task, workflow_session_id)

    async def track_llm_call_manually(self, execution_id: str, provider: str, model: str, prompt: str, response: str, **kwargs):
        """Manually track LLM call."""
        if not self._initialized or not self.obs_manager:
            return

        await self.obs_manager.track_llm_call(execution_id, provider, model, prompt, response, **kwargs)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive observability metrics."""
        if not self._initialized or not self.obs_manager:
            return {}

        try:
            real_time = await self.obs_manager.get_real_time_metrics()
            workflow_metrics = await self.obs_manager.get_workflow_metrics()
            agent_metrics = await self.obs_manager.get_agent_metrics()
            llm_metrics = await self.obs_manager.get_llm_metrics()
            daily_stats = await self.obs_manager.get_daily_stats(days=7)

            return {
                "real_time": real_time,
                "workflows": workflow_metrics,
                "agents": agent_metrics,
                "llm": llm_metrics,
                "daily_stats": daily_stats,
                "phoenix_url": f"http://{self.settings.PHOENIX_HOST}:{self.settings.PHOENIX_PORT}"
            }

        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            return {}

    def get_langgraph_hooks(self) -> Optional[LangGraphObservabilityHook]:
        """Get LangGraph observability hooks."""
        return self.langgraph_hook if self._initialized else None

    def get_crewai_hooks(self) -> Optional[CrewAIObservabilityHook]:
        """Get CrewAI observability hooks."""
        return self.crewai_hook if self._initialized else None

    @property
    def is_enabled(self) -> bool:
        """Check if observability is enabled and initialized."""
        return self._initialized and self.settings.OBSERVABILITY_ENABLED


# Global instance for easy access
_global_observability: Optional[NEOSObservabilityIntegration] = None


async def setup_observability(settings: Optional[Settings] = None) -> NEOSObservabilityIntegration:
    """
    Setup global observability integration.

    Args:
        settings: Optional settings instance

    Returns:
        NEOSObservabilityIntegration instance
    """
    global _global_observability

    if _global_observability is None:
        _global_observability = NEOSObservabilityIntegration(settings)

    if not _global_observability._initialized:
        await _global_observability.initialize()

    return _global_observability


async def shutdown_observability() -> None:
    """Shutdown global observability integration."""
    global _global_observability

    if _global_observability:
        await _global_observability.shutdown()
        _global_observability = None


def get_observability() -> Optional[NEOSObservabilityIntegration]:
    """Get global observability integration instance."""
    return _global_observability


# Convenience decorators using global instance
def trace_workflow(**kwargs):
    """Convenience decorator for workflow tracing using global instance."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **func_kwargs):
            obs = get_observability()
            if obs and obs.is_enabled:
                decorated_func = obs.trace_workflow(**kwargs)(func)
                return await decorated_func(*args, **func_kwargs)
            else:
                return await func(*args, **func_kwargs)

        return wrapper

    return decorator


def trace_agent(**kwargs):
    """Convenience decorator for agent tracing using global instance."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **func_kwargs):
            obs = get_observability()
            if obs and obs.is_enabled:
                decorated_func = obs.trace_agent(**kwargs)(func)
                return await decorated_func(*args, **func_kwargs)
            else:
                return await func(*args, **func_kwargs)

        return wrapper

    return decorator


def trace_llm_call(**kwargs):
    """Convenience decorator for LLM call tracing using global instance."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **func_kwargs):
            obs = get_observability()
            if obs and obs.is_enabled:
                decorated_func = obs.trace_llm_call(**kwargs)(func)
                return await decorated_func(*args, **func_kwargs)
            else:
                return await func(*args, **func_kwargs)

        return wrapper

    return decorator


# Integration helpers for existing NEOS components
class NEOSAgentObservabilityMixin:
    """
    Mixin class for NEOS agents to add observability.

    Add this to your agent classes to get automatic observability.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observability = get_observability()

    async def execute_with_observability(self, task: str, agent_type: Optional[str] = None, **kwargs):
        """Execute agent with observability tracking."""
        if not self._observability or not self._observability.is_enabled:
            # Fallback to regular execution
            return await self.execute(task, **kwargs)

        agent_id = getattr(self, 'agent_id', self.__class__.__name__)
        agent_type = agent_type or getattr(self, 'agent_type', self.__class__.__name__)

        async with self._observability.track_agent_manually(agent_id, agent_type, task) as execution_id:
            result = await self.execute(task, execution_id=execution_id, **kwargs)
            return result

    async def execute(self, task: str, **kwargs):
        """Override this method in your agent implementation."""
        raise NotImplementedError("Subclasses must implement execute method")


class NEOSWorkflowObservabilityMixin:
    """
    Mixin class for NEOS workflows to add observability.

    Add this to your workflow classes to get automatic observability.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observability = get_observability()

    async def run_with_observability(self, workflow_type: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, **kwargs):
        """Run workflow with observability tracking."""
        if not self._observability or not self._observability.is_enabled:
            # Fallback to regular execution
            return await self.run(**kwargs)

        workflow_id = getattr(self, 'workflow_id', self.__class__.__name__)
        workflow_type = workflow_type or getattr(self, 'workflow_type', self.__class__.__name__)

        async with self._observability.track_workflow_manually(workflow_id, workflow_type, metadata) as session_id:
            result = await self.run(workflow_session_id=session_id, **kwargs)
            return result

    async def run(self, **kwargs):
        """Override this method in your workflow implementation."""
        raise NotImplementedError("Subclasses must implement run method")


# FastAPI integration helper
def add_observability_to_fastapi(app, settings: Optional[Settings] = None, **middleware_kwargs):
    """
    Add observability to FastAPI application.

    Args:
        app: FastAPI application instance
        settings: Optional settings instance
        **middleware_kwargs: Additional middleware configuration
    """
    async def setup_obs():
        obs = await setup_observability(settings)
        if obs.is_enabled:
            middleware = obs.get_middleware(**middleware_kwargs)
            app.add_middleware(type(middleware), **middleware.__dict__)
            logger.info("Observability middleware added to FastAPI")

    async def shutdown_obs():
        await shutdown_observability()

    app.add_event_handler("startup", setup_obs)
    app.add_event_handler("shutdown", shutdown_obs)

    # Add metrics endpoint
    @app.get("/api/v1/observability/metrics")
    async def get_observability_metrics():
        """Get observability metrics."""
        obs = get_observability()
        if obs and obs.is_enabled:
            return await obs.get_metrics()
        return {"error": "Observability not enabled"}

    @app.get("/api/v1/observability/health")
    async def get_observability_health():
        """Get observability health status."""
        obs = get_observability()
        return {
            "enabled": obs.is_enabled if obs else False,
            "initialized": obs._initialized if obs else False,
            "phoenix_url": f"http://{settings.PHOENIX_HOST}:{settings.PHOENIX_PORT}" if settings else None
        }


# CLI integration helper
def add_observability_commands(cli_app):
    """
    Add observability commands to CLI application.

    Args:
        cli_app: CLI application instance (like Click app)
    """
    @cli_app.command()
    async def observability_status():
        """Check observability status."""
        obs = get_observability()
        if obs:
            print(f"Observability enabled: {obs.is_enabled}")
            print(f"Observability initialized: {obs._initialized}")
            if obs.is_enabled:
                metrics = await obs.get_metrics()
                print(f"Phoenix UI: {metrics.get('phoenix_url')}")
                print(f"Real-time metrics: {metrics.get('real_time')}")
        else:
            print("Observability not setup")

    @cli_app.command()
    async def observability_metrics():
        """Get observability metrics."""
        obs = get_observability()
        if obs and obs.is_enabled:
            metrics = await obs.get_metrics()
            print("=== Observability Metrics ===")
            for key, value in metrics.items():
                print(f"{key}: {value}")
        else:
            print("Observability not enabled or not setup")

    return cli_app