"""
Middleware for NEOS observability.
Automatic observability integration for FastAPI and other frameworks.
"""

import logging
import time
from typing import Any, Dict, Optional
from datetime import datetime
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .core import ObservabilityManager


logger = logging.getLogger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for automatic observability tracking.

    Tracks:
    - HTTP requests and responses
    - Request/response times
    - Error rates
    - API usage patterns
    """

    def __init__(
        self,
        app,
        observability_manager: ObservabilityManager,
        track_requests: bool = True,
        track_responses: bool = True,
        track_errors: bool = True,
        exclude_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.observability_manager = observability_manager
        self.track_requests = track_requests
        self.track_responses = track_responses
        self.track_errors = track_errors
        self.exclude_paths = exclude_paths or ["/health", "/metrics", "/docs", "/openapi.json"]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request and response with observability tracking."""
        # Skip tracking for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Generate request ID
        request_id = str(uuid.uuid4())
        start_time = time.time()
        start_datetime = datetime.now()

        # Extract request info
        request_info = {
            'request_id': request_id,
            'method': request.method,
            'url': str(request.url),
            'path': request.url.path,
            'query_params': dict(request.query_params),
            'headers': dict(request.headers),
            'client_ip': request.client.host if request.client else None,
            'user_agent': request.headers.get('user-agent'),
            'start_time': start_datetime
        }

        # Start request tracking
        if self.track_requests and self.observability_manager._initialized:
            await self._track_request_start(request_info)

        response = None

        try:
            # Process request
            response = await call_next(request)

            # Extract response info
            end_time = time.time()
            duration = end_time - start_time

            response_info = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'duration': duration,
                'end_time': datetime.now()
            }

            # Track successful response
            if self.track_responses and self.observability_manager._initialized:
                await self._track_request_end(request_id, request_info, response_info)

        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time

            error_info = {
                'error': str(e),
                'error_type': type(e).__name__,
                'duration': duration,
                'end_time': datetime.now()
            }

            # Track error
            if self.track_errors and self.observability_manager._initialized:
                await self._track_request_error(request_id, request_info, error_info)

            raise

        return response

    async def _track_request_start(self, request_info: Dict[str, Any]) -> None:
        """Track request start."""
        try:
            # Start a workflow session for the API request
            workflow_id = f"api_request_{request_info['method']}_{request_info['path']}"
            metadata = {
                'request_id': request_info['request_id'],
                'method': request_info['method'],
                'path': request_info['path'],
                'client_ip': request_info['client_ip'],
                'user_agent': request_info['user_agent']
            }

            session_id = await self.observability_manager.start_workflow_session(
                workflow_id=workflow_id,
                workflow_type="api_request",
                metadata=metadata
            )

            # Store session ID for later use
            request_info['session_id'] = session_id

        except Exception as e:
            logger.error(f"Failed to track request start: {e}")

    async def _track_request_end(self, request_id: str, request_info: Dict[str, Any], response_info: Dict[str, Any]) -> None:
        """Track successful request completion."""
        try:
            session_id = request_info.get('session_id')
            if not session_id:
                return

            result = {
                'status_code': response_info['status_code'],
                'duration': response_info['duration'],
                'success': response_info['status_code'] < 400
            }

            await self.observability_manager.end_workflow_session(
                session_id=session_id,
                result=result
            )

            # Track metrics
            if self.observability_manager.metrics_collector:
                await self.observability_manager.metrics_collector.record_llm_call({
                    'timestamp': datetime.now(),
                    'provider': 'api',
                    'model': f"{request_info['method']} {request_info['path']}",
                    'prompt_length': 0,
                    'response_length': 0,
                    'tokens_used': None,
                    'cost': None
                })

        except Exception as e:
            logger.error(f"Failed to track request end: {e}")

    async def _track_request_error(self, request_id: str, request_info: Dict[str, Any], error_info: Dict[str, Any]) -> None:
        """Track request error."""
        try:
            session_id = request_info.get('session_id')
            if not session_id:
                return

            await self.observability_manager.end_workflow_session(
                session_id=session_id,
                error=error_info['error']
            )

        except Exception as e:
            logger.error(f"Failed to track request error: {e}")


class LangGraphObservabilityHook:
    """
    Observability hooks for LangGraph workflows.

    Integrates with LangGraph's checkpoint and streaming systems.
    """

    def __init__(self, observability_manager: ObservabilityManager):
        self.observability_manager = observability_manager
        self._active_workflows: Dict[str, str] = {}  # thread_id -> session_id

    async def on_workflow_start(self, thread_id: str, config: Dict[str, Any]) -> None:
        """Called when a LangGraph workflow starts."""
        try:
            if not self.observability_manager._initialized:
                return

            workflow_id = config.get('workflow_id', f"langgraph_{thread_id}")
            workflow_type = config.get('workflow_type', 'langgraph_workflow')
            metadata = {
                'thread_id': thread_id,
                'config': config,
                'framework': 'langgraph'
            }

            session_id = await self.observability_manager.start_workflow_session(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                metadata=metadata
            )

            self._active_workflows[thread_id] = session_id

            logger.debug(f"Started LangGraph workflow tracking: {thread_id}")

        except Exception as e:
            logger.error(f"Failed to track LangGraph workflow start: {e}")

    async def on_workflow_end(self, thread_id: str, result: Any = None, error: str = None) -> None:
        """Called when a LangGraph workflow ends."""
        try:
            session_id = self._active_workflows.get(thread_id)
            if not session_id:
                return

            await self.observability_manager.end_workflow_session(
                session_id=session_id,
                result=result,
                error=error
            )

            # Remove from active workflows
            del self._active_workflows[thread_id]

            logger.debug(f"Ended LangGraph workflow tracking: {thread_id}")

        except Exception as e:
            logger.error(f"Failed to track LangGraph workflow end: {e}")

    async def on_node_start(self, thread_id: str, node_name: str, input_data: Any) -> None:
        """Called when a LangGraph node starts executing."""
        try:
            if not self.observability_manager._initialized:
                return

            workflow_session_id = self._active_workflows.get(thread_id)
            if not workflow_session_id:
                return

            agent_id = f"langgraph_node_{node_name}"
            task = f"Execute node: {node_name}"

            execution_id = await self.observability_manager.start_agent_execution(
                agent_id=agent_id,
                agent_type="langgraph_node",
                task=task,
                workflow_session_id=workflow_session_id
            )

            # Store execution ID for later use
            if not hasattr(self, '_active_nodes'):
                self._active_nodes = {}
            self._active_nodes[f"{thread_id}_{node_name}"] = execution_id

            logger.debug(f"Started LangGraph node tracking: {thread_id}/{node_name}")

        except Exception as e:
            logger.error(f"Failed to track LangGraph node start: {e}")

    async def on_node_end(self, thread_id: str, node_name: str, result: Any = None, error: str = None) -> None:
        """Called when a LangGraph node ends executing."""
        try:
            if not hasattr(self, '_active_nodes'):
                return

            execution_id = self._active_nodes.get(f"{thread_id}_{node_name}")
            if not execution_id:
                return

            await self.observability_manager.end_agent_execution(
                execution_id=execution_id,
                result=result,
                error=error
            )

            # Remove from active nodes
            del self._active_nodes[f"{thread_id}_{node_name}"]

            logger.debug(f"Ended LangGraph node tracking: {thread_id}/{node_name}")

        except Exception as e:
            logger.error(f"Failed to track LangGraph node end: {e}")


class CrewAIObservabilityHook:
    """
    Observability hooks for CrewAI agents.

    Integrates with CrewAI's agent execution and crew workflows.
    """

    def __init__(self, observability_manager: ObservabilityManager):
        self.observability_manager = observability_manager
        self._active_crews: Dict[str, str] = {}  # crew_id -> session_id
        self._active_agents: Dict[str, str] = {}  # agent_execution_id -> execution_id

    async def on_crew_start(self, crew_id: str, crew_config: Dict[str, Any]) -> None:
        """Called when a CrewAI crew starts."""
        try:
            if not self.observability_manager._initialized:
                return

            workflow_id = f"crewai_crew_{crew_id}"
            workflow_type = "crewai_crew"
            metadata = {
                'crew_id': crew_id,
                'crew_config': crew_config,
                'framework': 'crewai'
            }

            session_id = await self.observability_manager.start_workflow_session(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                metadata=metadata
            )

            self._active_crews[crew_id] = session_id

            logger.debug(f"Started CrewAI crew tracking: {crew_id}")

        except Exception as e:
            logger.error(f"Failed to track CrewAI crew start: {e}")

    async def on_crew_end(self, crew_id: str, result: Any = None, error: str = None) -> None:
        """Called when a CrewAI crew ends."""
        try:
            session_id = self._active_crews.get(crew_id)
            if not session_id:
                return

            await self.observability_manager.end_workflow_session(
                session_id=session_id,
                result=result,
                error=error
            )

            # Remove from active crews
            del self._active_crews[crew_id]

            logger.debug(f"Ended CrewAI crew tracking: {crew_id}")

        except Exception as e:
            logger.error(f"Failed to track CrewAI crew end: {e}")

    async def on_agent_start(self, crew_id: str, agent_id: str, agent_role: str, task: str) -> None:
        """Called when a CrewAI agent starts executing a task."""
        try:
            if not self.observability_manager._initialized:
                return

            workflow_session_id = self._active_crews.get(crew_id)

            execution_id = await self.observability_manager.start_agent_execution(
                agent_id=agent_id,
                agent_type=f"crewai_{agent_role}",
                task=task,
                workflow_session_id=workflow_session_id
            )

            self._active_agents[f"{crew_id}_{agent_id}"] = execution_id

            logger.debug(f"Started CrewAI agent tracking: {crew_id}/{agent_id}")

        except Exception as e:
            logger.error(f"Failed to track CrewAI agent start: {e}")

    async def on_agent_end(self, crew_id: str, agent_id: str, result: Any = None, error: str = None) -> None:
        """Called when a CrewAI agent ends executing a task."""
        try:
            execution_id = self._active_agents.get(f"{crew_id}_{agent_id}")
            if not execution_id:
                return

            await self.observability_manager.end_agent_execution(
                execution_id=execution_id,
                result=result,
                error=error
            )

            # Remove from active agents
            del self._active_agents[f"{crew_id}_{agent_id}"]

            logger.debug(f"Ended CrewAI agent tracking: {crew_id}/{agent_id}")

        except Exception as e:
            logger.error(f"Failed to track CrewAI agent end: {e}")

    async def on_llm_call(self, agent_id: str, provider: str, model: str, prompt: str, response: str, tokens_used: Optional[int] = None, cost: Optional[float] = None) -> None:
        """Called when a CrewAI agent makes an LLM call."""
        try:
            if not self.observability_manager._initialized:
                return

            # Find the active execution ID for this agent
            execution_id = None
            for key, exec_id in self._active_agents.items():
                if key.endswith(f"_{agent_id}"):
                    execution_id = exec_id
                    break

            if not execution_id:
                execution_id = f"unknown_{agent_id}"

            await self.observability_manager.track_llm_call(
                execution_id=execution_id,
                provider=provider,
                model=model,
                prompt=prompt,
                response=response,
                tokens_used=tokens_used,
                cost=cost
            )

            logger.debug(f"Tracked CrewAI LLM call: {agent_id}")

        except Exception as e:
            logger.error(f"Failed to track CrewAI LLM call: {e}")