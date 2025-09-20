"""
Decorators for NEOS observability.
Provides easy-to-use decorators for tracing workflows, agents, and LLM calls.
"""

import functools
import logging
from typing import Any, Callable, Dict, Optional
from datetime import datetime
import inspect

from .core import ObservabilityManager


logger = logging.getLogger(__name__)


def trace_workflow(
    workflow_id: Optional[str] = None,
    workflow_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    observability_manager: Optional[ObservabilityManager] = None
):
    """
    Decorator for tracing workflow execution.

    Args:
        workflow_id: Custom workflow ID (defaults to function name)
        workflow_type: Type of workflow (defaults to function name)
        metadata: Additional metadata to include in trace
        observability_manager: ObservabilityManager instance

    Example:
        @trace_workflow(workflow_type="search_workflow")
        async def search_workflow(query: str):
            # Workflow implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                # If no observability manager or not initialized, just call the function
                return await func(*args, **kwargs)

            # Extract workflow info
            wf_id = workflow_id or func.__name__
            wf_type = workflow_type or func.__name__
            wf_metadata = metadata or {}

            # Add function info to metadata
            wf_metadata.update({
                'function_name': func.__name__,
                'module': func.__module__,
                'args_count': len(args),
                'kwargs_keys': list(kwargs.keys())
            })

            async with observability_manager.trace_workflow(wf_id, wf_type, wf_metadata) as session_id:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(f"Workflow {wf_id} failed: {e}")
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                return func(*args, **kwargs)

            # For sync functions, we need to run in async context
            logger.warning(f"Sync function {func.__name__} used with trace_workflow. Consider using async version.")
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def trace_agent(
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    task_param: str = "task",
    observability_manager: Optional[ObservabilityManager] = None
):
    """
    Decorator for tracing agent execution.

    Args:
        agent_id: Custom agent ID (defaults to function name)
        agent_type: Type of agent (defaults to function name)
        task_param: Parameter name that contains the task description
        observability_manager: ObservabilityManager instance

    Example:
        @trace_agent(agent_type="search_agent")
        async def execute_search(task: str, context: dict):
            # Agent implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                return await func(*args, **kwargs)

            # Extract agent info
            a_id = agent_id or func.__name__
            a_type = agent_type or func.__name__

            # Extract task from parameters
            task = "Unknown task"
            if task_param in kwargs:
                task = str(kwargs[task_param])
            elif len(args) > 0 and hasattr(args[0], task_param):
                task = str(getattr(args[0], task_param))

            # Try to get workflow session ID from context
            workflow_session_id = kwargs.get('workflow_session_id')
            if not workflow_session_id and len(args) > 0:
                # Check if first argument has workflow_session_id
                if hasattr(args[0], 'workflow_session_id'):
                    workflow_session_id = getattr(args[0], 'workflow_session_id')

            async with observability_manager.trace_agent(a_id, a_type, task, workflow_session_id) as execution_id:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(f"Agent {a_id} failed: {e}")
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                return func(*args, **kwargs)

            logger.warning(f"Sync function {func.__name__} used with trace_agent. Consider using async version.")
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def trace_llm_call(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_param: str = "prompt",
    response_param: str = "response",
    observability_manager: Optional[ObservabilityManager] = None
):
    """
    Decorator for tracing LLM API calls.

    Args:
        provider: LLM provider name
        model: Model name
        prompt_param: Parameter name for prompt
        response_param: Parameter name for response (in return value)
        observability_manager: ObservabilityManager instance

    Example:
        @trace_llm_call(provider="openai", model="gpt-4")
        async def call_openai(prompt: str, model: str = "gpt-4"):
            # LLM call implementation
            return response
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                return await func(*args, **kwargs)

            # Extract prompt
            prompt = "Unknown prompt"
            if prompt_param in kwargs:
                prompt = str(kwargs[prompt_param])
            elif len(args) > 0:
                prompt = str(args[0])

            # Extract provider and model info
            llm_provider = provider or kwargs.get('provider', 'unknown')
            llm_model = model or kwargs.get('model', 'unknown')

            start_time = datetime.now()

            try:
                result = await func(*args, **kwargs)

                # Extract response
                response = "Unknown response"
                if isinstance(result, dict) and response_param in result:
                    response = str(result[response_param])
                elif isinstance(result, str):
                    response = result
                elif hasattr(result, response_param):
                    response = str(getattr(result, response_param))

                # Extract usage info if available
                tokens_used = None
                cost = None

                if isinstance(result, dict):
                    tokens_used = result.get('tokens_used') or result.get('usage', {}).get('total_tokens')
                    cost = result.get('cost')

                # Try to get current execution ID from context
                execution_id = kwargs.get('execution_id', 'unknown')

                # Track the LLM call
                await observability_manager.track_llm_call(
                    execution_id=execution_id,
                    provider=llm_provider,
                    model=llm_model,
                    prompt=prompt,
                    response=response,
                    tokens_used=tokens_used,
                    cost=cost
                )

                return result

            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            if not observability_manager or not observability_manager._initialized:
                return func(*args, **kwargs)

            logger.warning(f"Sync function {func.__name__} used with trace_llm_call. Consider using async version.")
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class ObservabilityDecorator:
    """
    Class-based decorator for more complex observability scenarios.

    Allows for dynamic configuration and state management.
    """

    def __init__(self, observability_manager: ObservabilityManager):
        self.observability_manager = observability_manager

    def workflow(
        self,
        workflow_id: Optional[str] = None,
        workflow_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Class-based workflow decorator."""
        return trace_workflow(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            metadata=metadata,
            observability_manager=self.observability_manager
        )

    def agent(
        self,
        agent_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        task_param: str = "task"
    ):
        """Class-based agent decorator."""
        return trace_agent(
            agent_id=agent_id,
            agent_type=agent_type,
            task_param=task_param,
            observability_manager=self.observability_manager
        )

    def llm_call(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prompt_param: str = "prompt",
        response_param: str = "response"
    ):
        """Class-based LLM call decorator."""
        return trace_llm_call(
            provider=provider,
            model=model,
            prompt_param=prompt_param,
            response_param=response_param,
            observability_manager=self.observability_manager
        )


def create_observability_decorators(observability_manager: ObservabilityManager) -> ObservabilityDecorator:
    """
    Factory function to create observability decorators with a specific manager.

    Args:
        observability_manager: ObservabilityManager instance

    Returns:
        ObservabilityDecorator instance

    Example:
        obs = create_observability_decorators(observability_manager)

        @obs.workflow(workflow_type="analysis")
        async def analyze_data(data):
            pass

        @obs.agent(agent_type="search")
        async def search_knowledge(task):
            pass
    """
    return ObservabilityDecorator(observability_manager)