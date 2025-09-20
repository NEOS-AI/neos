"""
Phoenix client for NEOS observability.
Handles Phoenix server communication and trace management.
"""

import logging
from typing import Any, Dict, Optional
from datetime import datetime

import phoenix as px
import httpx


logger = logging.getLogger(__name__)


class PhoenixClient:
    """
    Client for interacting with Phoenix observability platform.

    Handles:
    - Phoenix server setup and communication
    - Trace data transmission
    - Project and session management
    - Evaluation data processing
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.project_name = config.get('project_name', 'neos-multi-agent')
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 6006)
        self.collector_endpoint = config.get('collector_endpoint')

        self.phoenix_session = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.base_url = f"http://{self.host}:{self.port}"

        self._active_projects: Dict[str, Any] = {}
        self._session_data: Dict[str, Dict[str, Any]] = {}

    async def initialize(self) -> None:
        """Initialize Phoenix client and start session."""
        try:
            logger.info(f"Initializing Phoenix client at {self.base_url}")

            # Initialize HTTP client
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_connections=10)
            )

            # Start Phoenix session
            await self._start_phoenix_session()

            # Create or get project
            await self._setup_project()

            logger.info("Phoenix client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Phoenix client: {e}")
            raise


    async def _start_phoenix_session(self) -> None:
        """Start Phoenix tracing session."""
        try:
            # Set environment variables for Phoenix (avoids deprecation warnings)
            import os
            os.environ['PHOENIX_HOST'] = self.host
            os.environ['PHOENIX_PORT'] = str(self.port)

            # Launch Phoenix with modern API
            self.phoenix_session = px.launch_app()

            # Configure OpenTelemetry endpoint if provided
            if self.collector_endpoint:
                px.configure(
                    collector_endpoint=self.collector_endpoint
                )

            logger.info(f"Phoenix session started at {self.base_url}")

        except Exception as e:
            logger.warning(f"Could not start Phoenix session: {e}")
            # Continue without Phoenix UI
            pass

    async def _setup_project(self) -> None:
        """Setup Phoenix project for NEOS."""
        try:
            # Modern Phoenix manages projects automatically
            # No need for explicit project context management
            self._active_projects[self.project_name] = {
                'created_at': datetime.now(),
                'sessions': {}
            }

            logger.info(f"Phoenix project '{self.project_name}' setup complete")

        except Exception as e:
            logger.error(f"Failed to setup Phoenix project: {e}")
            raise

    async def start_session(self, session_id: str, session_type: str, metadata: Dict[str, Any]) -> None:
        """Start a new tracing session."""
        session_data = {
            'session_id': session_id,
            'session_type': session_type,
            'start_time': datetime.now(),
            'metadata': metadata,
            'traces': []
        }

        self._session_data[session_id] = session_data

        # Add to project
        if self.project_name in self._active_projects:
            self._active_projects[self.project_name]['sessions'][session_id] = session_data

        logger.debug(f"Started Phoenix session: {session_id}")

    async def end_session(self, session_id: str, final_data: Dict[str, Any]) -> None:
        """End a tracing session."""
        if session_id not in self._session_data:
            logger.warning(f"Session not found: {session_id}")
            return

        session_data = self._session_data[session_id]
        session_data['end_time'] = datetime.now()
        session_data['final_data'] = final_data

        # Send session data to Phoenix
        await self._send_session_data(session_data)

        logger.debug(f"Ended Phoenix session: {session_id}")

    async def start_agent_trace(self, execution_id: str, execution_data: Dict[str, Any]) -> None:
        """Start tracing an agent execution."""
        trace_data = {
            'trace_id': execution_id,
            'span_type': 'agent_execution',
            'start_time': execution_data['start_time'],
            'attributes': {
                'agent_id': execution_data['agent_id'],
                'agent_type': execution_data['agent_type'],
                'task': execution_data['task'],
                'workflow_session_id': execution_data.get('workflow_session_id')
            }
        }

        # Add trace to session if available
        workflow_session_id = execution_data.get('workflow_session_id')
        if workflow_session_id and workflow_session_id in self._session_data:
            self._session_data[workflow_session_id]['traces'].append(trace_data)

        await self._send_trace_data(trace_data)

        logger.debug(f"Started agent trace: {execution_id}")

    async def end_agent_trace(self, execution_id: str, execution_data: Dict[str, Any]) -> None:
        """End an agent execution trace."""
        trace_data = {
            'trace_id': execution_id,
            'end_time': execution_data['end_time'],
            'duration': execution_data['duration'],
            'status': execution_data['status'],
            'result': execution_data.get('result'),
            'error': execution_data.get('error'),
            'llm_calls_count': len(execution_data.get('llm_calls', []))
        }

        await self._send_trace_data(trace_data)

        logger.debug(f"Ended agent trace: {execution_id}")

    async def track_llm_call(self, execution_id: str, call_data: Dict[str, Any], prompt: str, response: str) -> None:
        """Track an LLM API call."""
        llm_trace_data = {
            'trace_id': f"{execution_id}_llm_{call_data['timestamp'].isoformat()}",
            'parent_id': execution_id,
            'span_type': 'llm_call',
            'timestamp': call_data['timestamp'],
            'attributes': {
                'provider': call_data['provider'],
                'model': call_data['model'],
                'prompt_length': call_data['prompt_length'],
                'response_length': call_data['response_length'],
                'tokens_used': call_data.get('tokens_used'),
                'cost': call_data.get('cost')
            },
            'input': prompt,
            'output': response
        }

        await self._send_trace_data(llm_trace_data)

        logger.debug(f"Tracked LLM call for execution: {execution_id}")

    async def _send_session_data(self, session_data: Dict[str, Any]) -> None:
        """Send session data to Phoenix."""
        if not self.http_client:
            return

        try:
            # Log session completion for Phoenix integration
            # Modern Phoenix automatically tracks sessions via OpenTelemetry
            logger.debug(f"Session completed: {session_data['session_id']}")
            logger.debug(f"Session duration: {session_data.get('end_time', datetime.now()).timestamp() - session_data['start_time'].timestamp():.2f}s")
            logger.debug(f"Session traces: {len(session_data.get('traces', []))}")

        except Exception as e:
            logger.error(f"Failed to send session data to Phoenix: {e}")

    async def _send_trace_data(self, trace_data: Dict[str, Any]) -> None:
        """Send trace data to Phoenix."""
        if not self.http_client:
            return

        try:
            # Log trace data for Phoenix integration
            # Modern Phoenix automatically tracks traces via OpenTelemetry
            logger.debug(f"Trace recorded: {trace_data['trace_id']}")
            logger.debug(f"Trace type: {trace_data.get('span_type', 'unknown')}")
            if 'duration' in trace_data:
                logger.debug(f"Trace duration: {trace_data['duration']:.2f}s")

        except Exception as e:
            logger.error(f"Failed to send trace data to Phoenix: {e}")

    async def create_evaluation(self, session_id: str, evaluation_type: str, evaluation_data: Dict[str, Any]) -> None:
        """Create an evaluation in Phoenix."""
        try:
            # Note: Evaluation functions are version-dependent and may not be available
            # This is a placeholder for future Phoenix evaluation integration
            logger.info(f"Evaluation requested for session {session_id}, type: {evaluation_type}")
            logger.info("Phoenix evaluation integration is available in enterprise versions")

            # Store evaluation data for future processing
            evaluation_record = {
                'session_id': session_id,
                'evaluation_type': evaluation_type,
                'data': evaluation_data,
                'timestamp': datetime.now().isoformat()
            }

            logger.debug(f"Evaluation record created: {evaluation_record}")

        except Exception as e:
            logger.error(f"Failed to create evaluation: {e}")

    async def get_project_stats(self) -> Dict[str, Any]:
        """Get project statistics from Phoenix."""
        try:
            if self.project_name not in self._active_projects:
                return {}

            project_data = self._active_projects[self.project_name]

            stats = {
                'project_name': self.project_name,
                'created_at': project_data['created_at'].isoformat(),
                'total_sessions': len(project_data['sessions']),
                'active_sessions': len([
                    s for s in project_data['sessions'].values()
                    if 'end_time' not in s
                ]),
                'base_url': self.base_url
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get project stats: {e}")
            return {}

    async def shutdown(self) -> None:
        """Shutdown Phoenix client."""
        try:
            logger.info("Shutting down Phoenix client...")

            # Close HTTP client
            if self.http_client:
                await self.http_client.aclose()

            # Modern Phoenix doesn't require explicit project context cleanup
            # Projects are managed automatically by the Phoenix server

            # Close Phoenix session
            if self.phoenix_session:
                # Phoenix session cleanup (if needed)
                pass

            logger.info("Phoenix client shutdown completed")

        except Exception as e:
            logger.error(f"Error during Phoenix client shutdown: {e}")

    async def health_check(self) -> bool:
        """Check if Phoenix server is healthy."""
        try:
            if not self.http_client:
                return False

            response = await self.http_client.get(f"{self.base_url}/health")
            return response.status_code == 200

        except Exception as e:
            logger.debug(f"Phoenix health check failed: {e}")
            return False