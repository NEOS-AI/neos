from typing import Dict, Any, Optional
from datetime import datetime
import hashlib
import logging
from langgraph.graph import StateGraph, START, END

from neos.agents.search_agents import (
    KnowledgeSearchAgent,
    RealtimeInfoSearchAgent,
    RealtimeDataSearchAgent,
    MultiQuerySearchAgent,
    WebLookUpAgent
)
from neos.agents.analysis_agents import (
    DataAnalysisAgent,
    ComparativeAnalysisAgent,
    WebLookupAgent as WebContentAnalysisAgent
)
from neos.agents.generation_agents import (
    ImageGenerationAgent,
    ApiCallAgent,
    FileProcessingAgent,
    TaskCreationAgent
)
from neos.agents.skill_based_tool_selector import SkillBasedToolSelector
from neos.utils.cache import cache_manager
from neos.utils.smart_cache_manager import smart_cache_manager
from neos.config.settings import settings
from neos.tools.tool_selector import tool_selector

from .state import AgentState, WorkflowConfig
from .orchestrators import SearchOrchestrator, AnalysisOrchestrator, GenerationOrchestrator
from .processors import ResultProcessor, QualityValidator, ResponseGenerator, ConversationContextProcessor
from .utils import QueryClassifier
from .checkpointer import get_checkpointer
from .events import WorkflowEventHandler, NullEventHandler


logger = logging.getLogger(__name__)


class MultiAgentWorkflow:
    """
    리팩토링된 멀티 에이전트 워크플로우 관리 클래스

    Enterprise features:
    - Distributed state management with PostgreSQL checkpointer
    - Horizontal scalability
    - Session persistence across restarts
    """

    def __init__(self):
        self.config = WorkflowConfig()
        self.agents = self._initialize_agents()

        # 컴포넌트 초기화
        self.conversation_context_processor = ConversationContextProcessor()
        self.query_classifier = QueryClassifier(self.config)
        self.skill_tool_selector = SkillBasedToolSelector()
        self.search_orchestrator = SearchOrchestrator(self.agents, self.config, tool_selector)
        self.analysis_orchestrator = AnalysisOrchestrator(self.agents, self.config)
        self.generation_orchestrator = GenerationOrchestrator(self.agents, self.config)
        self.result_processor = ResultProcessor()
        self.quality_validator = QualityValidator(self.config)
        self.response_generator = ResponseGenerator()

        # 워크플로우 그래프 생성 (비동기로 초기화)
        self.graph = None
        self._graph_initialized = False
        self._graph_uses_checkpointer = False


    def _initialize_agents(self) -> Dict[str, Any]:
        """에이전트 초기화"""
        logger.debug("Initializing agents...")

        agents = {
            # 검색 에이전트들
            "knowledge_search": KnowledgeSearchAgent(),
            "realtime_info_search": RealtimeInfoSearchAgent(),
            "realtime_data_search": RealtimeDataSearchAgent(),
            "multi_query_search": MultiQuerySearchAgent(),
            "web_lookup": WebLookUpAgent(),

            # 분석 에이전트들
            "data_analysis": DataAnalysisAgent(),
            "comparative_analysis": ComparativeAnalysisAgent(),
            "web_content_analysis": WebContentAnalysisAgent(),

            # 생성 에이전트들
            "image_generation": ImageGenerationAgent(),
            "api_call": ApiCallAgent(),
            "file_processing": FileProcessingAgent(),
            "task_creation": TaskCreationAgent()
        }

        logger.debug(f"Initialized {len(agents)} agents")
        return agents


    async def _create_workflow_graph(self, use_checkpointer: bool = True) -> StateGraph:
        """
        워크플로우 그래프 생성 (Enterprise Edition with PostgreSQL Checkpointer)

        Args:
            use_checkpointer: Whether to use PostgreSQL checkpointer for state persistence
                            Set to False for single-request workflows (like chat API)
        """
        logger.debug(f"Creating workflow graph (checkpointer={'enabled' if use_checkpointer else 'disabled'})...")

        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("conversation_context_processor", self._process_conversation_context_node)
        workflow.add_node("query_classifier", self._classify_query_node)
        workflow.add_node("skill_tool_selector", self._select_skills_tools_node)
        workflow.add_node("search_orchestrator", self._orchestrate_search_node)
        workflow.add_node("analysis_orchestrator", self._orchestrate_analysis_node)
        workflow.add_node("generation_orchestrator", self._orchestrate_generation_node)
        workflow.add_node("result_integrator", self._integrate_results_node)
        workflow.add_node("quality_validator", self._validate_quality_node)
        workflow.add_node("response_generator", self._generate_response_node)

        # 엣지 정의
        # 조건부 진입점: 히스토리가 있으면 context processor를 거치고, 없으면 바로 query_classifier로
        workflow.add_conditional_edges(
            START,
            self._should_process_context,
            {
                "process_context": "conversation_context_processor",
                "skip_context": "query_classifier"
            }
        )

        workflow.add_edge("conversation_context_processor", "query_classifier")
        workflow.add_edge("query_classifier", "skill_tool_selector")
        workflow.add_edge("skill_tool_selector", "search_orchestrator")
        workflow.add_edge("search_orchestrator", "analysis_orchestrator")
        workflow.add_edge("analysis_orchestrator", "generation_orchestrator")
        workflow.add_edge("generation_orchestrator", "result_integrator")
        workflow.add_edge("result_integrator", "quality_validator")

        # 조건부 엣지 (품질 검증 결과에 따라)
        workflow.add_conditional_edges(
            "quality_validator",
            self._should_regenerate,
            {
                "regenerate": "search_orchestrator",  # 품질이 낮으면 다시 검색
                "proceed": "response_generator"       # 품질이 좋으면 응답 생성
            }
        )

        workflow.add_edge("response_generator", END)

        # Conditionally use checkpointer
        if use_checkpointer:
            checkpointer = await get_checkpointer()
            print("[DEBUG] Workflow graph created with PostgreSQL checkpointer for horizontal scaling")
            return workflow.compile(checkpointer=checkpointer)
        else:
            print("[DEBUG] Workflow graph created without checkpointer (stateless mode)")
            return workflow.compile()


    async def _ensure_graph_initialized(self, use_checkpointer: bool = True):
        """
        Ensure graph is initialized before use.

        Args:
            use_checkpointer: Whether to use checkpointer for state persistence
        """
        if not self._graph_initialized:
            self.graph = await self._create_workflow_graph(use_checkpointer=use_checkpointer)
            self._graph_initialized = True
            self._graph_uses_checkpointer = use_checkpointer


    async def _classify_query_node(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 노드"""
        return await self.query_classifier.classify_query(state)

    async def _select_skills_tools_node(self, state: AgentState) -> Dict[str, Any]:
        """Skill and Tool selection 노드"""
        print("[DEBUG] Executing skill/tool selection node")

        try:
            query = state.get("original_query", "")
            session_id = state.get("session_id", "")
            user_id = state.get("user_id", "")
            detected_language = state.get("detected_language", "ko")

            # Build context from query classification
            query_classification = state.get("query_classification", {})
            selection_context = {
                "intent": state.get("query_intent", "unknown"),
                "query_type": query_classification.get("query_type", "general"),
                "complexity": query_classification.get("complexity", "medium"),
                "required_agents": state.get("required_agents", []),
                "requires_analysis": "data_analysis" in state.get("required_agents", []),
                "requires_search": any(
                    agent in state.get("required_agents", [])
                    for agent in [
                        "knowledge_search", "realtime_info_search", "multi_query_search",
                    ]
                )
            }

            # Call skill/tool selector
            selection = await self.skill_tool_selector.select_skills_and_tools(
                query=query,
                context=selection_context,
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )

            print(f"[DEBUG] Selected {len(selection.selected_skills)} skills: {selection.selected_skills}")
            print(f"[DEBUG] Selected {len(selection.selected_tools)} tools: {selection.selected_tools}")

            # Return state updates
            return {
                "selected_skills": selection.selected_skills,
                "selected_tools": selection.selected_tools,
                "selection_reasoning": selection.reasoning
            }

        except Exception as e:
            print(f"[ERROR] Skill/tool selection failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            # Return empty selections on error
            return {
                "selected_skills": [],
                "selected_tools": [],
                "selection_reasoning": f"Selection failed: {str(e)}"
            }

    async def _process_conversation_context_node(self, state: AgentState) -> Dict[str, Any]:
        """대화 컨텍스트 처리 노드"""
        return await self.conversation_context_processor.process(state)

    async def _orchestrate_search_node(self, state: AgentState) -> Dict[str, Any]:
        """검색 오케스트레이션 노드"""
        return await self.search_orchestrator.orchestrate(state)

    async def _orchestrate_analysis_node(self, state: AgentState) -> Dict[str, Any]:
        """분석 오케스트레이션 노드"""
        return await self.analysis_orchestrator.orchestrate(state)

    async def _orchestrate_generation_node(self, state: AgentState) -> Dict[str, Any]:
        """생성 오케스트레이션 노드"""
        return await self.generation_orchestrator.orchestrate(state)

    async def _integrate_results_node(self, state: AgentState) -> Dict[str, Any]:
        """결과 통합 노드"""
        return await self.result_processor.integrate_results(state)

    async def _validate_quality_node(self, state: AgentState) -> Dict[str, Any]:
        """품질 검증 노드"""
        return await self.quality_validator.validate_quality(state)

    async def _generate_response_node(self, state: AgentState) -> Dict[str, Any]:
        """응답 생성 노드"""
        return await self.response_generator.generate_response(state)

    def _should_process_context(self, state: AgentState) -> str:
        """
        대화 컨텍스트 처리 여부 결정

        히스토리가 있고 활성화되어 있으면 context processor를 거치고,
        없으면 바로 query_classifier로 이동
        """
        has_history = bool(state.get("chat_history"))
        context_enabled = state.get("enable_history_context", False)

        if has_history and context_enabled:
            return "process_context"
        return "skip_context"

    def _should_regenerate(self, state: AgentState) -> str:
        """재생성 여부 결정"""
        return self.quality_validator.should_regenerate(state)


    async def execute_workflow(
        self,
        user_input: Dict[str, Any],
        event_handler: Optional[WorkflowEventHandler] = None,
        use_checkpointer: bool = True
    ) -> Dict[str, Any]:
        """
        워크플로우 실행 (Enterprise Edition with distributed state)

        스마트 캐시 통합:
        - pgvector 기반 의미론적 유사 쿼리 캐싱
        - 쿼리 유형별 동적 TTL

        Args:
            user_input: 워크플로우 입력 데이터
            event_handler: 이벤트 핸들러 (Dependency Injection)
                          None이면 NullEventHandler 사용 (성능 오버헤드 없음)
            use_checkpointer: Whether to use PostgreSQL checkpointer for state persistence
                            Set to False for single-request workflows (like chat API)
        """
        # Null Object Pattern: event_handler가 없으면 기본 핸들러 사용
        if event_handler is None:
            event_handler = NullEventHandler()

        # Ensure graph is initialized
        await self._ensure_graph_initialized(use_checkpointer=use_checkpointer)

        query = user_input["query"]
        user_id = user_input.get("user_id")
        print(f"[DEBUG] Starting workflow execution for query: {query[:50]}...")

        # 워크플로우 시작 이벤트
        await event_handler.on_workflow_start(user_input)

        # 1. 스마트 캐시 확인 (활성화된 경우)
        if settings.SMART_CACHE_ENABLED:
            smart_cache_result = await self._check_smart_cache(query, user_id)
            if smart_cache_result:
                # 캐시 히트 시에도 완료 이벤트 발행
                await event_handler.on_workflow_complete(smart_cache_result)
                return smart_cache_result

        # 2. 기존 Redis 캐시 확인 (폴백)
        cache_key = self._generate_cache_key(query, user_id)
        cached_response = await self._check_cached_response(cache_key)
        if cached_response:
            await event_handler.on_workflow_complete(cached_response)
            return cached_response

        # 초기 상태 생성 (event_handler를 상태에 포함)
        initial_state = self._create_initial_state(user_input)
        initial_state["_event_handler"] = event_handler

        try:
            # 워크플로우 실행
            if use_checkpointer:
                print("[DEBUG] Executing workflow graph with distributed state management...")
                config = {
                    "configurable": {"thread_id": user_input["session_id"]},
                    "recursion_limit": 50  # 재시도를 위한 recursion limit 증가
                }
            else:
                print("[DEBUG] Executing workflow graph in stateless mode...")
                config = {
                    "recursion_limit": 50  # 재시도를 위한 recursion limit 증가
                }

            # 노드별 진행 상황 추적을 위해 astream 사용
            workflow_nodes = [
                "query_classifier",
                "skill_tool_selector",
                "search_orchestrator",
                "analysis_orchestrator",
                "generation_orchestrator",
                "result_integrator",
                "quality_validator",
                "response_generator"
            ]

            current_step = 0
            total_steps = len(workflow_nodes)
            final_state = None

            # 스트리밍으로 워크플로우 실행하며 이벤트 emit
            async for chunk in self.graph.astream(initial_state, config):
                # chunk는 {node_name: state} 형식
                for node_name, state in chunk.items():
                    if node_name in workflow_nodes:
                        current_step += 1

                        # 노드 시작 이벤트
                        await event_handler.on_node_start(
                            node_name, current_step, total_steps
                        )

                        # 노드 완료 이벤트 (state에서 필요한 정보 추출)
                        node_result = {
                            "node": node_name,
                            "step": current_step
                        }
                        await event_handler.on_node_complete(node_name, node_result)

                    # 마지막 상태 저장
                    final_state = state

            # 결과 생성
            result = self._create_workflow_result(final_state)

            # 성공적인 결과 캐싱
            if result["success"] and result["response"]:
                # 스마트 캐시에 저장 (활성화된 경우)
                if settings.SMART_CACHE_ENABLED:
                    await self._save_to_smart_cache(
                        query=query,
                        result=result,
                        final_state=final_state,
                        user_id=user_id,
                        session_id=user_input.get("session_id")
                    )

                # 기존 Redis 캐시에도 저장 (폴백용)
                await self._cache_workflow_result(cache_key, result)

            # 데이터셋 자동 저장 (LLM 호출이 있었을 경우)
            await self._auto_save_dataset()

            # 워크플로우 완료 이벤트
            await event_handler.on_workflow_complete(result)

            print("[DEBUG] Workflow execution completed successfully")
            return result

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Workflow execution failed: {str(e)}")

            # 에러 이벤트
            await event_handler.on_workflow_error(e)

            return self._create_error_result(e, initial_state)

    async def _check_smart_cache(
        self,
        query: str,
        user_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        스마트 캐시에서 유사 쿼리 검색

        pgvector를 사용하여 의미론적으로 유사한 캐시된 응답을 찾습니다.
        """
        try:
            print("[DEBUG] Checking smart cache (pgvector semantic search)...")

            cache_result = await smart_cache_manager.get_cached_response(
                query=query,
                user_id=user_id
            )

            if cache_result.hit:
                response = cache_result.response
                print(
                    f"[DEBUG] Smart cache HIT: type={cache_result.hit_type}, "
                    f"similarity={response.similarity_score:.3f}, "
                    f"search_time={cache_result.search_time_ms}ms"
                )

                # 캐시된 응답 반환
                result = response.response_data.copy()
                result["cache_hit"] = True
                result["smart_cache_hit"] = True
                result["cache_hit_type"] = cache_result.hit_type
                result["similarity_score"] = response.similarity_score
                result["original_query"] = response.query_text
                result["timestamp"] = datetime.utcnow().isoformat()

                return result

            print(
                f"[DEBUG] Smart cache MISS: search_time={cache_result.search_time_ms}ms"
            )
            return None

        except Exception as e:
            print(f"[WARNING] Smart cache check failed: {e}")
            return None

    async def _save_to_smart_cache(
        self,
        query: str,
        result: Dict[str, Any],
        final_state: AgentState,
        user_id: str = None,
        session_id: str = None
    ) -> None:
        """
        결과를 스마트 캐시에 저장

        동적 TTL: 쿼리 의도, 복잡도, 품질 점수에 따라 자동 계산
        """
        try:
            # 쿼리 임베딩 가져오기
            query_embedding = final_state.get("query_embedding")
            if not query_embedding:
                print("[DEBUG] No query embedding available, skipping smart cache save")
                return

            # 쿼리 분류 정보 가져오기
            classification = final_state.get("query_classification", {})
            query_intent = final_state.get("query_intent", "information_seeking")
            complexity_score = classification.get("complexity_score", 0.0)
            quality_score = result.get("quality_score", 0.7)

            # 캐시할 데이터 준비 (cache_hit 정보 제외)
            cache_data = {k: v for k, v in result.items() if k != "cache_hit"}

            # 스마트 캐시에 저장
            success = await smart_cache_manager.set_cached_response(
                query=query,
                query_vector=query_embedding,
                query_intent=query_intent,
                complexity_score=complexity_score,
                response_data=cache_data,
                quality_score=quality_score,
                user_id=user_id,
                session_id=session_id,
                metadata={
                    "required_agents": final_state.get("required_agents", []),
                    "execution_steps": final_state.get("execution_steps", []),
                    "detected_language": final_state.get("detected_language")
                }
            )

            if success:
                print(
                    f"[DEBUG] Smart cache saved: intent={query_intent}, "
                    f"complexity={complexity_score:.2f}, quality={quality_score:.2f}"
                )
            else:
                print("[WARNING] Failed to save to smart cache")

        except Exception as e:
            print(f"[WARNING] Smart cache save failed: {e}")


    def _generate_cache_key(self, query: str, user_id: Optional[str] = None) -> str:
        """
        캐시 키 생성

        Args:
            query: 쿼리 텍스트
            user_id: 사용자 ID (선택적, USER_SPECIFIC_CACHE가 활성화된 경우 사용)

        Returns:
            생성된 캐시 키
        """
        query_normalized = query.strip().lower()

        # 사용자별 캐시 분리 옵션 (개인화된 응답이 필요한 경우)
        if user_id and settings.USER_SPECIFIC_CACHE:
            cache_input = f"<USER_ID>{user_id}</USER_ID>{query_normalized}"
        else:
            cache_input = query_normalized

        query_hash = hashlib.md5(cache_input.encode('utf-8')).hexdigest()
        return cache_manager.make_key("workflow_response", query_hash)


    async def _check_cached_response(self, cache_key: str) -> Dict[str, Any]:
        """캐시된 응답 확인"""
        print(f"[DEBUG] Checking workflow response cache with key: {cache_key}")
        cached_response = await cache_manager.get(cache_key, deserialize="json")

        if cached_response:
            print("[DEBUG] Found cached workflow response, returning cached result")
            cached_response["cache_hit"] = True
            cached_response["timestamp"] = datetime.utcnow().isoformat()
            return cached_response

        print("[DEBUG] No cached response found, executing workflow")
        return None

    def _create_initial_state(self, user_input: Dict[str, Any]) -> AgentState:
        """초기 상태 생성"""
        return AgentState(
            user_id=user_input["user_id"],
            session_id=user_input["session_id"],
            original_query=user_input["query"],
            query_intent=None,
            query_embedding=None,
            detected_language=None,
            query_classification=None,
            required_agents=[],
            search_results=[],
            analysis_results=[],
            generation_results=[],
            search_synthesis=None,  # Phase 2: LLM 검색 결과 종합
            search_metadata=None,  # Phase 2: 검색 메타데이터
            integrated_results=None,
            quality_score=None,
            quality_feedback=None,
            final_response=None,
            response_metadata=None,
            execution_start=datetime.utcnow(),
            execution_steps=[],
            errors=[],
            retry_count=0,
            execution_time_ms=None,
            tokens_used=None,
            api_calls_made=None
        )

    def _create_workflow_result(self, final_state: AgentState) -> Dict[str, Any]:
        """워크플로우 결과 생성"""
        return {
            "success": True,
            "response": final_state["final_response"],
            "metadata": final_state["response_metadata"],
            "execution_time_ms": final_state["execution_time_ms"],
            "quality_score": final_state.get("quality_score", 0.0),
            "errors": final_state["errors"],
            "cache_hit": False,
            "execution_steps": len(final_state["execution_steps"]),
            "retry_count": final_state.get("retry_count", 0)
        }

    def _create_error_result(self, error: Exception, initial_state: AgentState) -> Dict[str, Any]:
        """오류 결과 생성"""
        return {
            "success": False,
            "error": str(error),
            "partial_state": initial_state,
            "cache_hit": False,
            "execution_time_ms": int((datetime.utcnow() - initial_state["execution_start"]).total_seconds() * 1000)
        }

    async def _cache_workflow_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """워크플로우 결과 캐싱"""
        print(f"[DEBUG] Caching workflow response for {settings.WORKFLOW_RESPONSE_CACHE_TTL} seconds")

        # 캐시할 때는 cache_hit 정보 제외
        cache_data = {k: v for k, v in result.items() if k != "cache_hit"}

        await cache_manager.set(
            cache_key,
            cache_data,
            ttl=settings.WORKFLOW_RESPONSE_CACHE_TTL,
            serialize="json"
        )

        print("[DEBUG] Workflow response cached successfully")

    async def _auto_save_dataset(self) -> None:
        """워크플로우 실행 후 데이터셋 자동 저장"""
        # 자동 저장이 비활성화되어 있으면 건너뛰기
        if not settings.DATASET_AUTO_SAVE:
            return

        from neos.dataset import llm_call_collector, dataset_manager

        # 수집된 레코드 확인
        stats = llm_call_collector.get_statistics()
        record_count = stats.get("total_records", 0)

        if record_count > 0:
            try:
                print(f"[DEBUG] Auto-saving dataset with {record_count} records...")

                # 설정된 형식으로 저장
                save_format = settings.DATASET_SAVE_FORMAT.lower()

                if save_format == "json":
                    filepath = dataset_manager.save_json(include_metadata=True)
                elif save_format == "csv":
                    filepath = dataset_manager.save_csv()
                else:  # 기본값: jsonl
                    filepath = dataset_manager.save_jsonl(include_metadata=True)

                if filepath:
                    print(f"[DEBUG] Dataset auto-saved to: {filepath}")

                    # 저장 후 메모리 정리 (선택적 - 계속 수집하려면 주석 처리)
                    # llm_call_collector.clear_records()
                else:
                    print("[DEBUG] No dataset records to save")

            except Exception as e:
                print(f"[WARNING] Failed to auto-save dataset: {e}")
        else:
            print("[DEBUG] No LLM calls recorded, skipping dataset save")

    # 유틸리티 메서드들
    def get_workflow_stats(self) -> Dict[str, Any]:
        """워크플로우 통계 정보"""
        return {
            "agent_count": len(self.agents),
            "search_agents": len([a for a in self.agents.keys() if "search" in a]),
            "analysis_agents": len([a for a in self.agents.keys() if "analysis" in a]),
            "generation_agents": len([a for a in self.agents.keys() if "generation" in a]),
            "components_initialized": {
                "query_classifier": bool(self.query_classifier),
                "search_orchestrator": bool(self.search_orchestrator),
                "analysis_orchestrator": bool(self.analysis_orchestrator),
                "generation_orchestrator": bool(self.generation_orchestrator),
                "result_processor": bool(self.result_processor),
                "quality_validator": bool(self.quality_validator),
                "response_generator": bool(self.response_generator)
            },
            "config": {
                "max_retries": self.config.MAX_RETRIES,
                "min_quality_score": self.config.MIN_QUALITY_SCORE
            }
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        워크플로우 상태 확인 (Enterprise Edition)
        Includes checkpointer health status and smart cache statistics
        """
        health_status = {
            "workflow": "healthy",
            "components": {},
            "agents": len(self.agents),
            "timestamp": datetime.utcnow().isoformat(),
            "state_management": "distributed"
        }

        # 컴포넌트 상태 확인
        try:
            health_status["components"]["query_classifier"] = "healthy"
            health_status["components"]["orchestrators"] = "healthy"
            health_status["components"]["processors"] = "healthy"

            # Check graph initialization
            if self._graph_initialized:
                health_status["components"]["graph"] = "healthy"
            else:
                health_status["components"]["graph"] = "initializing"

            # Check PostgreSQL checkpointer
            try:
                checkpointer = await get_checkpointer()
                stats = await checkpointer.get_stats()
                health_status["components"]["checkpointer"] = "healthy"
                health_status["checkpointer_stats"] = stats
            except Exception as e:
                health_status["components"]["checkpointer"] = f"error: {str(e)}"

            # Check Smart Cache status
            if settings.SMART_CACHE_ENABLED:
                try:
                    cache_stats = await smart_cache_manager.get_cache_statistics(hours=24)
                    health_status["components"]["smart_cache"] = "healthy"
                    health_status["smart_cache_stats"] = {
                        "enabled": True,
                        "hit_rate_percent": cache_stats.get("hit_rate_percent", 0),
                        "cache_entries": cache_stats.get("cache_entries", 0),
                        "total_requests_24h": cache_stats.get("total_requests", 0),
                        "semantic_hits_24h": cache_stats.get("semantic_hits", 0),
                        "exact_hits_24h": cache_stats.get("exact_hits", 0),
                        "similarity_threshold": cache_stats.get("similarity_threshold", 0.85)
                    }
                except Exception as e:
                    health_status["components"]["smart_cache"] = f"error: {str(e)}"
                    health_status["smart_cache_stats"] = {"enabled": True, "error": str(e)}
            else:
                health_status["components"]["smart_cache"] = "disabled"
                health_status["smart_cache_stats"] = {"enabled": False}

        except Exception as e:
            health_status["workflow"] = f"error: {str(e)}"

        return health_status


# 전역 워크플로우 인스턴스 (리팩토링된 버전)
multi_agent_workflow = MultiAgentWorkflow()