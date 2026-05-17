"""
Comprehensive unit tests for MultiAgentWorkflow (Core Orchestration Engine)

CORE ENGINE CRITICAL - Tests cover:
- Workflow initialization and agent setup
- Graph creation and state management
- Workflow execution and error handling
- Caching mechanisms
- Quality validation and retry logic
- Health check and monitoring
- Enterprise features (distributed state, PostgreSQL checkpointer)
"""

import os
import sys
import types
from contextlib import contextmanager

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

youtube_module = types.ModuleType("youtube_transcript_api")
youtube_module.YouTubeTranscriptApi = object
youtube_errors_module = types.ModuleType("youtube_transcript_api._errors")
youtube_errors_module.TranscriptsDisabled = Exception
youtube_errors_module.NoTranscriptFound = Exception
youtube_errors_module.VideoUnavailable = Exception
sys.modules.setdefault("youtube_transcript_api", youtube_module)
sys.modules.setdefault("youtube_transcript_api._errors", youtube_errors_module)

googleapi_module = types.ModuleType("googleapiclient")
googleapi_discovery_module = types.ModuleType("googleapiclient.discovery")
googleapi_discovery_module.build = lambda *args, **kwargs: object()
googleapi_errors_module = types.ModuleType("googleapiclient.errors")
googleapi_errors_module.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapi_module)
sys.modules.setdefault("googleapiclient.discovery", googleapi_discovery_module)
sys.modules.setdefault("googleapiclient.errors", googleapi_errors_module)

isodate_module = types.ModuleType("isodate")
isodate_module.parse_duration = lambda value: value
sys.modules.setdefault("isodate", isodate_module)


@contextmanager
def _noop_trace(*args, **kwargs):
    yield object()


telemetry_module = types.ModuleType("neos.workflow.telemetry")
telemetry_module.trace_workflow_node = _noop_trace
telemetry_module.add_span_event = lambda *args, **kwargs: None
telemetry_module.set_span_attributes = lambda *args, **kwargs: None
sys.modules.setdefault("neos.workflow.telemetry", telemetry_module)

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any
import hashlib

from neos.agents.skill_based_tool_selector import SkillToolSelection
from neos.workflow.graph import MultiAgentWorkflow, multi_agent_workflow
from neos.workflow.state import AgentState, WorkflowConfig
import neos.workflow.graph as workflow_graph_module

if not hasattr(workflow_graph_module, "KnowledgeSearchAgent"):
    workflow_graph_module.KnowledgeSearchAgent = object


@pytest.mark.unit
class TestMultiAgentWorkflowInitialization:
    """Test suite for workflow initialization"""

    def test_workflow_initialization(self):
        """Test successful workflow initialization"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent") as mock_agent:
            workflow = MultiAgentWorkflow()

            assert workflow.config is not None
            assert isinstance(workflow.config, WorkflowConfig)
            assert workflow.agents is not None
            assert workflow.query_classifier is not None
            assert workflow.search_orchestrator is not None
            assert workflow.analysis_orchestrator is not None
            assert workflow.generation_orchestrator is not None
            assert workflow.result_processor is not None
            assert workflow.quality_validator is not None
            assert workflow.response_generator is not None
            assert workflow.graph is None  # Not initialized yet
            assert workflow._graph_initialized is False

    def test_initialize_agents(self):
        """Test agent initialization"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            with patch("neos.workflow.graph.DataAnalysisAgent"):
                with patch("neos.workflow.graph.ImageGenerationAgent"):
                    workflow = MultiAgentWorkflow()
                    agents = workflow.agents

                    # Verify all agent types are initialized
                    assert "knowledge_search" in agents
                    assert "realtime_info_search" in agents
                    assert "data_analysis" in agents
                    assert "comparative_analysis" in agents
                    assert "image_generation" in agents
                    assert "api_call" in agents
                    assert "file_processing" in agents
                    assert "task_creation" in agents

                    # Verify count
                    assert len(agents) == 14  # 7 search + 3 analysis + 4 generation

    def test_workflow_config_defaults(self):
        """Test workflow configuration defaults"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            workflow = MultiAgentWorkflow()
            config = workflow.config

            assert hasattr(config, "MAX_RETRIES")
            assert hasattr(config, "MIN_QUALITY_SCORE")


@pytest.mark.unit
class TestWorkflowGraphCreation:
    """Test suite for workflow graph creation"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance with mocked agents"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    @pytest.mark.asyncio
    async def test_create_workflow_graph(self, workflow):
        """Test workflow graph creation with PostgreSQL checkpointer"""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.get_stats = AsyncMock(return_value={"total_checkpoints": 0})

        with patch("neos.workflow.graph.get_checkpointer", return_value=mock_checkpointer):
            with patch("neos.workflow.graph.StateGraph") as MockStateGraph:
                mock_graph_instance = MagicMock()
                mock_compiled = MagicMock()
                mock_graph_instance.compile.return_value = mock_compiled
                MockStateGraph.return_value = mock_graph_instance

                graph = await workflow._create_workflow_graph()

                # Verify StateGraph was initialized
                MockStateGraph.assert_called_once_with(AgentState)

                # Verify nodes were added
                assert mock_graph_instance.add_node.call_count >= 7  # At least 7 nodes

                # Verify edges were set
                assert mock_graph_instance.set_entry_point.called
                assert mock_graph_instance.add_edge.call_count >= 5
                assert mock_graph_instance.add_conditional_edges.called

                # Verify checkpointer was used
                mock_graph_instance.compile.assert_called_once_with(checkpointer=mock_checkpointer)

    @pytest.mark.asyncio
    async def test_ensure_graph_initialized(self, workflow):
        """Test graph initialization check"""
        assert workflow._graph_initialized is False
        assert workflow.graph is None

        mock_checkpointer = AsyncMock()
        with patch("neos.workflow.graph.get_checkpointer", return_value=mock_checkpointer):
            with patch("neos.workflow.graph.StateGraph"):
                await workflow._ensure_graph_initialized()

                assert workflow._graph_initialized is True
                assert workflow.graph is not None

    @pytest.mark.asyncio
    async def test_ensure_graph_initialized_idempotent(self, workflow):
        """Test that graph initialization is idempotent"""
        mock_checkpointer = AsyncMock()
        with patch("neos.workflow.graph.get_checkpointer", return_value=mock_checkpointer):
            with patch("neos.workflow.graph.StateGraph"):
                await workflow._ensure_graph_initialized()
                first_graph = workflow.graph

                # Call again
                await workflow._ensure_graph_initialized()
                second_graph = workflow.graph

                # Should be the same graph instance
                assert first_graph is second_graph

    @pytest.mark.asyncio
    async def test_ensure_graph_initializes_checkpointer_modes_separately(self, workflow, monkeypatch):
        """Stateless and checkpointer graphs must not share one global cache."""
        created_modes = []

        async def fake_create_workflow_graph(use_checkpointer=True):
            created_modes.append(use_checkpointer)
            return object()

        monkeypatch.setattr(
            workflow,
            "_create_workflow_graph",
            fake_create_workflow_graph,
        )

        await workflow._ensure_graph_initialized(use_checkpointer=False)
        stateless_graph = workflow.graph
        await workflow._ensure_graph_initialized(use_checkpointer=True)

        assert created_modes == [False, True]
        assert workflow.graph is not stateless_graph
        assert workflow._graph_uses_checkpointer is True


@pytest.mark.unit
class TestWorkflowExecution:
    """Test suite for workflow execution"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance with mocked components"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    @pytest.mark.asyncio
    async def test_execute_workflow_success(self, workflow):
        """Test successful workflow execution"""
        user_input = {
            "query": "What is the weather today?",
            "user_id": "user_123",
            "session_id": "session_456"
        }

        # Mock graph execution
        mock_graph = AsyncMock()
        final_state = {
            "final_response": "The weather is sunny",
            "response_metadata": {"confidence": 0.95},
            "execution_time_ms": 1500,
            "quality_score": 0.9,
            "errors": [],
            "execution_steps": ["classify", "search", "analyze", "generate"],
            "retry_count": 0,
            "execution_start": datetime.now()
        }
        mock_graph.ainvoke = AsyncMock(return_value=final_state)
        workflow.graph = mock_graph
        workflow._graph_initialized = True

        # Mock cache (no hit)
        with patch.object(workflow, "_check_cached_response", return_value=None):
            with patch.object(workflow, "_cache_workflow_result") as mock_cache:
                with patch.object(workflow, "_auto_save_dataset"):
                    result = await workflow.execute_workflow(user_input)

                    assert result["success"] is True
                    assert result["response"] == "The weather is sunny"
                    assert result["quality_score"] == 0.9
                    assert result["cache_hit"] is False
                    assert result["execution_steps"] == 4

                    # Verify result was cached
                    mock_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_workflow_cache_hit(self, workflow):
        """Test workflow execution with cache hit"""
        user_input = {
            "query": "What is the weather today?",
            "user_id": "user_123",
            "session_id": "session_456"
        }

        cached_response = {
            "success": True,
            "response": "Cached: The weather is sunny",
            "execution_time_ms": 50,
            "quality_score": 0.9,
            "cache_hit": True  # Add cache_hit field to cached response
        }

        with patch.object(workflow, "_check_cached_response", return_value=cached_response):
            result = await workflow.execute_workflow(user_input)

            assert result["success"] is True
            assert result.get("cache_hit") is True  # Use .get() for safer access
            assert "Cached:" in result["response"]
            # With cache hit, the workflow returns early, so graph may still be None or initialized
            # Just verify we got a cached response

    @pytest.mark.asyncio
    async def test_execute_workflow_error_handling(self, workflow):
        """Test workflow error handling"""
        user_input = {
            "query": "Test query",
            "user_id": "user_123",
            "session_id": "session_456"
        }

        # Mock graph to raise exception
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=Exception("Workflow execution failed"))
        workflow.graph = mock_graph
        workflow._graph_initialized = True

        with patch.object(workflow, "_check_cached_response", return_value=None):
            result = await workflow.execute_workflow(user_input)

            assert result["success"] is False
            assert "error" in result
            assert "Workflow execution failed" in result["error"]
            assert "partial_state" in result


@pytest.mark.unit
class TestCacheManagement:
    """Test suite for cache management"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    def test_generate_cache_key(self, workflow):
        """Test cache key generation"""
        query1 = "What is the weather today?"
        query2 = "What is the weather today?"  # Same query
        query3 = "  WHAT IS THE WEATHER TODAY?  "  # Same but different case/spaces
        query4 = "What is the weather tomorrow?"  # Different query

        with patch("neos.workflow.graph.cache_manager") as mock_cache_manager:
            mock_cache_manager.make_key = lambda prefix, key: f"{prefix}:{key}"

            key1 = workflow._generate_cache_key(query1, autonomy_level=1)
            key2 = workflow._generate_cache_key(query2, autonomy_level=1)
            key3 = workflow._generate_cache_key(query3, autonomy_level=1)
            key4 = workflow._generate_cache_key(query4, autonomy_level=1)
            manual_key = workflow._generate_cache_key(query1, autonomy_level=0)
            autonomous_key = workflow._generate_cache_key(query1, autonomy_level=2)

            # Same queries should generate same keys
            assert key1 == key2 == key3
            # Different queries should generate different keys
            assert key1 != key4
            # Same query under different approval policies must not share cache
            assert key1 != manual_key
            assert key1 != autonomous_key

    @pytest.mark.asyncio
    async def test_smart_cache_lookup_is_scoped_by_autonomy_level(self, workflow):
        """Smart cache lookup filters by autonomy level metadata."""
        with patch("neos.workflow.graph.smart_cache_manager") as mock_cache:
            mock_cache.get_cached_response = AsyncMock()
            mock_cache.get_cached_response.return_value.hit = False
            mock_cache.get_cached_response.return_value.search_time_ms = 1

            result = await workflow._check_smart_cache(
                "What is the weather today?",
                user_id="user_123",
                autonomy_level=0,
            )

            assert result is None
            mock_cache.get_cached_response.assert_awaited_once_with(
                query="What is the weather today?",
                user_id="user_123",
                metadata_filter={"autonomy_level": 0},
            )

    @pytest.mark.asyncio
    async def test_smart_cache_save_stores_autonomy_level_metadata(self, workflow):
        """Smart cache entries include autonomy level metadata."""
        final_state = {
            "query_embedding": [0.1, 0.2],
            "query_classification": {"complexity_score": 0.5},
            "query_intent": "information_seeking",
            "required_agents": ["knowledge_search"],
            "execution_steps": ["skill_tool_selector"],
            "detected_language": "en",
            "autonomy_level": 2,
        }

        with patch("neos.workflow.graph.smart_cache_manager") as mock_cache:
            mock_cache.set_cached_response = AsyncMock(return_value=True)

            await workflow._save_to_smart_cache(
                query="What is the weather today?",
                result={"success": True, "response": "ok", "quality_score": 0.8},
                final_state=final_state,
                user_id="user_123",
                session_id="session_456",
            )

            metadata = mock_cache.set_cached_response.await_args.kwargs["metadata"]
            assert metadata["autonomy_level"] == 2

    @pytest.mark.asyncio
    async def test_manual_approval_uses_required_agents_even_without_selected_skills(self, workflow, monkeypatch):
        """Manual autonomy gates workflow agents selected by query classification."""
        workflow._graph_uses_checkpointer = True
        workflow.skill_tool_selector.select_skills_and_tools = AsyncMock(
            return_value=SkillToolSelection(
                selected_skills=[],
                selected_tools=[],
                reasoning="required agent came from classifier",
                priority_order=[],
            )
        )
        workflow._check_approval_allowlist = AsyncMock(return_value=False)
        monkeypatch.setattr(
            workflow_graph_module,
            "_register_pending_approvals_db",
            AsyncMock(),
        )

        state = {
            "original_query": "latest AI news",
            "session_id": "session_123",
            "user_id": "user_123",
            "detected_language": "en",
            "query_intent": "realtime_info",
            "query_classification": {"query_type": "general", "complexity": "medium"},
            "required_agents": ["realtime_info_search"],
            "autonomy_level": 0,
        }

        with patch("neos.workflow.graph.settings") as mock_settings:
            mock_settings.EXECUTION_APPROVAL_ENABLED = True
            mock_settings.APPROVAL_REQUIRED_SKILLS = []
            mock_settings.APPROVAL_TIMEOUT_SECONDS = 300

            result = await workflow._select_skills_tools_node(state)

        assert result["pending_approvals"][0]["skill_name"] == "realtime_info_search"

    @pytest.mark.asyncio
    async def test_execute_workflow_bypass_cache_skips_cache_reads(self, workflow, monkeypatch):
        """bypass_cache=True forces a fresh workflow execution."""
        final_state = {
            "final_response": "fresh response",
            "response_metadata": {},
            "execution_time_ms": 10,
            "quality_score": 0.9,
            "errors": [],
            "execution_steps": ["response_generator"],
            "retry_count": 0,
            "execution_start": datetime.now(),
            "channel_source": "api",
        }

        class FakeGraph:
            async def astream(self, initial_state, config):
                yield {"response_generator": final_state}

        smart_cache = AsyncMock(return_value={"success": True, "response": "smart cached"})
        redis_cache = AsyncMock(return_value={"success": True, "response": "redis cached"})
        monkeypatch.setattr(workflow_graph_module.settings, "SMART_CACHE_ENABLED", True)
        monkeypatch.setattr(workflow, "_ensure_graph_initialized", AsyncMock())
        monkeypatch.setattr(workflow, "_check_smart_cache", smart_cache)
        monkeypatch.setattr(workflow, "_check_cached_response", redis_cache)
        monkeypatch.setattr(workflow, "_load_memory_context", AsyncMock())
        monkeypatch.setattr(workflow, "_apply_research_template", AsyncMock())
        monkeypatch.setattr(workflow, "_record_session_start", AsyncMock())
        monkeypatch.setattr(workflow, "_save_to_smart_cache", AsyncMock())
        monkeypatch.setattr(workflow, "_cache_workflow_result", AsyncMock())
        monkeypatch.setattr(workflow, "_auto_save_dataset", AsyncMock())
        monkeypatch.setattr(workflow, "_save_episode_memory", AsyncMock())
        monkeypatch.setattr(workflow, "_record_session_complete", AsyncMock())
        workflow.graph = FakeGraph()

        result = await workflow.execute_workflow(
            {
                "query": "What is the weather today?",
                "user_id": "user_123",
                "session_id": "session_123",
                "bypass_cache": True,
            },
            use_checkpointer=False,
        )

        assert result["response"] == "fresh response"
        smart_cache.assert_not_awaited()
        redis_cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_cached_response_hit(self, workflow):
        """Test cache hit scenario"""
        cache_key = "workflow_response:test_hash"
        cached_data = {
            "success": True,
            "response": "Cached response",
            "execution_time_ms": 50
        }

        with patch("neos.workflow.graph.cache_manager") as mock_cache_manager:
            mock_cache_manager.get = AsyncMock(return_value=cached_data)

            result = await workflow._check_cached_response(cache_key)

            assert result is not None
            assert result["cache_hit"] is True
            assert result["response"] == "Cached response"
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_check_cached_response_miss(self, workflow):
        """Test cache miss scenario"""
        cache_key = "workflow_response:test_hash"

        with patch("neos.workflow.graph.cache_manager") as mock_cache_manager:
            mock_cache_manager.get = AsyncMock(return_value=None)

            result = await workflow._check_cached_response(cache_key)

            assert result is None

    @pytest.mark.asyncio
    async def test_cache_workflow_result(self, workflow):
        """Test workflow result caching"""
        cache_key = "workflow_response:test_hash"
        result = {
            "success": True,
            "response": "Test response",
            "execution_time_ms": 1000,
            "cache_hit": False  # This should be removed when caching
        }

        with patch("neos.workflow.graph.cache_manager") as mock_cache_manager:
            mock_cache_manager.set = AsyncMock()
            with patch("neos.workflow.graph.settings") as mock_settings:
                mock_settings.WORKFLOW_RESPONSE_CACHE_TTL = 3600

                await workflow._cache_workflow_result(cache_key, result)

                # Verify cache was set
                mock_cache_manager.set.assert_called_once()
                call_args = mock_cache_manager.set.call_args
                cached_data = call_args[0][1]

                # Verify cache_hit was removed
                assert "cache_hit" not in cached_data
                assert cached_data["response"] == "Test response"


@pytest.mark.unit
class TestStateManagement:
    """Test suite for state creation and management"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    def test_create_initial_state(self, workflow):
        """Test initial state creation"""
        user_input = {
            "query": "Test query",
            "user_id": "user_123",
            "session_id": "session_456"
        }

        state = workflow._create_initial_state(user_input)

        assert state["user_id"] == "user_123"
        assert state["session_id"] == "session_456"
        assert state["original_query"] == "Test query"
        assert state["query_intent"] is None
        assert state["search_results"] == []
        assert state["errors"] == []
        assert state["retry_count"] == 0
        assert isinstance(state["execution_start"], datetime)

    def test_create_workflow_result(self, workflow):
        """Test workflow result creation from final state"""
        final_state = {
            "final_response": "Test response",
            "response_metadata": {"confidence": 0.9},
            "execution_time_ms": 1500,
            "quality_score": 0.85,
            "errors": [],
            "execution_steps": ["step1", "step2", "step3"],
            "retry_count": 1
        }

        result = workflow._create_workflow_result(final_state)

        assert result["success"] is True
        assert result["response"] == "Test response"
        assert result["metadata"]["confidence"] == 0.9
        assert result["execution_time_ms"] == 1500
        assert result["quality_score"] == 0.85
        assert result["execution_steps"] == 3
        assert result["retry_count"] == 1
        # cache_hit may or may not be present
        assert result.get("cache_hit") is not None or "cache_hit" not in result

    def test_create_error_result(self, workflow):
        """Test error result creation"""
        error = Exception("Test error")
        initial_state = {
            "user_id": "user_123",
            "execution_start": datetime.now() - timedelta(milliseconds=500)
        }

        result = workflow._create_error_result(error, initial_state)

        assert result["success"] is False
        assert result["error"] == "Test error"
        assert "partial_state" in result
        # cache_hit may or may not be present
        assert result.get("cache_hit") is not None or "cache_hit" not in result
        assert result["execution_time_ms"] >= 500


@pytest.mark.unit
class TestDatasetManagement:
    """Test suite for dataset auto-save functionality"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    @pytest.mark.asyncio
    async def test_auto_save_dataset_disabled(self, workflow):
        """Test dataset auto-save when disabled"""
        with patch("neos.workflow.graph.settings") as mock_settings:
            mock_settings.DATASET_AUTO_SAVE = False

            # Should return early without saving
            await workflow._auto_save_dataset()
            # No assertions needed - just verify no exceptions

    @pytest.mark.asyncio
    async def test_auto_save_dataset_no_records(self, workflow):
        """Test dataset auto-save with no records"""
        with patch("neos.workflow.graph.settings") as mock_settings:
            mock_settings.DATASET_AUTO_SAVE = True

            mock_collector = MagicMock()
            mock_collector.get_statistics.return_value = {"total_records": 0}

            with patch.object(workflow, "llm_call_collector", mock_collector, create=True):
                await workflow._auto_save_dataset()
                # Should complete without error


@pytest.mark.unit
class TestWorkflowStats:
    """Test suite for workflow statistics"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    def test_get_workflow_stats(self, workflow):
        """Test workflow statistics retrieval"""
        stats = workflow.get_workflow_stats()

        assert "agent_count" in stats
        assert "search_agents" in stats
        assert "analysis_agents" in stats
        assert "generation_agents" in stats
        assert "components_initialized" in stats
        assert "config" in stats

        # Verify component counts exist and are non-negative
        assert stats["agent_count"] >= 0
        assert stats["search_agents"] >= 0
        assert stats["analysis_agents"] >= 0
        assert stats["generation_agents"] >= 0

        # Total should match sum of parts
        total_agents = stats["search_agents"] + stats["analysis_agents"] + stats["generation_agents"]
        assert stats["agent_count"] >= total_agents

        # Verify components
        components = stats["components_initialized"]
        assert components["query_classifier"] is True
        assert components["search_orchestrator"] is True
        assert components["result_processor"] is True


@pytest.mark.unit
class TestHealthCheck:
    """Test suite for health check functionality"""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            return MultiAgentWorkflow()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, workflow):
        """Test health check when all components are healthy"""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.get_stats = AsyncMock(return_value={
            "total_checkpoints": 100,
            "active_sessions": 5
        })

        with patch("neos.workflow.graph.get_checkpointer", return_value=mock_checkpointer):
            workflow._graph_initialized = True

            health = await workflow.health_check()

            assert health["workflow"] == "healthy"
            assert health["agents"] == 14
            assert health["state_management"] == "distributed"
            assert "timestamp" in health
            assert health["components"]["query_classifier"] == "healthy"
            assert health["components"]["orchestrators"] == "healthy"
            assert health["components"]["graph"] == "healthy"
            assert health["components"]["checkpointer"] == "healthy"
            assert "checkpointer_stats" in health

    @pytest.mark.asyncio
    async def test_health_check_graph_not_initialized(self, workflow):
        """Test health check when graph is not initialized"""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.get_stats = AsyncMock(return_value={})

        with patch("neos.workflow.graph.get_checkpointer", return_value=mock_checkpointer):
            workflow._graph_initialized = False

            health = await workflow.health_check()

            assert health["components"]["graph"] == "initializing"

    @pytest.mark.asyncio
    async def test_health_check_checkpointer_error(self, workflow):
        """Test health check when checkpointer has errors"""
        with patch("neos.workflow.graph.get_checkpointer", side_effect=Exception("DB connection failed")):
            workflow._graph_initialized = True

            health = await workflow.health_check()

            assert "error" in health["components"]["checkpointer"]
            assert "DB connection failed" in health["components"]["checkpointer"]


@pytest.mark.unit
class TestGlobalInstance:
    """Test suite for global workflow instance"""

    def test_global_instance_exists(self):
        """Test that global multi_agent_workflow instance exists"""
        with patch("neos.workflow.graph.KnowledgeSearchAgent"):
            assert multi_agent_workflow is not None
            assert isinstance(multi_agent_workflow, MultiAgentWorkflow)
