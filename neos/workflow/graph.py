from typing import Dict, Any
from datetime import datetime
import hashlib
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from neos.agents.search_agents import (
    KnowledgeSearchAgent,
    RealtimeInfoSearchAgent,
    RealtimeDataSearchAgent,
    MultiQuerySearchAgent,
    DeepResearchAgent
)
from neos.agents.analysis_agents import (
    DataAnalysisAgent,
    ComparativeAnalysisAgent
)
from neos.agents.generation_agents import (
    ImageGenerationAgent,
    ApiCallAgent,
    FileProcessingAgent,
    TaskCreationAgent
)
from neos.utils.cache import cache_manager
from neos.config.settings import settings
from neos.tools.tool_selector import tool_selector

from .state import AgentState, WorkflowConfig
from .orchestrators import SearchOrchestrator, AnalysisOrchestrator, GenerationOrchestrator
from .processors import ResultProcessor, QualityValidator, ResponseGenerator
from .utils import QueryClassifier


class MultiAgentWorkflow:
    """리팩토링된 멀티 에이전트 워크플로우 관리 클래스"""

    def __init__(self):
        self.config = WorkflowConfig()
        self.agents = self._initialize_agents()

        # 컴포넌트 초기화
        self.query_classifier = QueryClassifier(self.config)
        self.search_orchestrator = SearchOrchestrator(self.agents, self.config, tool_selector)
        self.analysis_orchestrator = AnalysisOrchestrator(self.agents, self.config)
        self.generation_orchestrator = GenerationOrchestrator(self.agents, self.config)
        self.result_processor = ResultProcessor()
        self.quality_validator = QualityValidator(self.config)
        self.response_generator = ResponseGenerator()

        # 워크플로우 그래프 생성
        self.graph = self._create_workflow_graph()


    def _initialize_agents(self) -> Dict[str, Any]:
        """에이전트 초기화"""
        print("[DEBUG] Initializing agents...")

        agents = {
            # 검색 에이전트들
            "knowledge_search": KnowledgeSearchAgent(),
            "realtime_info_search": RealtimeInfoSearchAgent(),
            "realtime_data_search": RealtimeDataSearchAgent(),
            "multi_query_search": MultiQuerySearchAgent(),
            "deep_research": DeepResearchAgent(),

            # 분석 에이전트들
            "data_analysis": DataAnalysisAgent(),
            "comparative_analysis": ComparativeAnalysisAgent(),

            # 생성 에이전트들
            "image_generation": ImageGenerationAgent(),
            "api_call": ApiCallAgent(),
            "file_processing": FileProcessingAgent(),
            "task_creation": TaskCreationAgent()
        }

        print(f"[DEBUG] Initialized {len(agents)} agents")
        return agents

    def _create_workflow_graph(self) -> StateGraph:
        """워크플로우 그래프 생성"""
        print("[DEBUG] Creating workflow graph...")

        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("query_classifier", self._classify_query_node)
        workflow.add_node("search_orchestrator", self._orchestrate_search_node)
        workflow.add_node("analysis_orchestrator", self._orchestrate_analysis_node)
        workflow.add_node("generation_orchestrator", self._orchestrate_generation_node)
        workflow.add_node("result_integrator", self._integrate_results_node)
        workflow.add_node("quality_validator", self._validate_quality_node)
        workflow.add_node("response_generator", self._generate_response_node)

        # 엣지 정의
        workflow.set_entry_point("query_classifier")

        workflow.add_edge("query_classifier", "search_orchestrator")
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

        print("[DEBUG] Workflow graph created successfully")
        return workflow.compile(checkpointer=MemorySaver())

    # 워크플로우 노드 메서드들
    async def _classify_query_node(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 노드"""
        return await self.query_classifier.classify_query(state)

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

    def _should_regenerate(self, state: AgentState) -> str:
        """재생성 여부 결정"""
        return self.quality_validator.should_regenerate(state)

    async def execute_workflow(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 실행"""
        query = user_input["query"]
        print(f"[DEBUG] Starting workflow execution for query: {query[:50]}...")

        # 캐시 키 생성
        cache_key = self._generate_cache_key(query)

        # 캐시된 응답 확인
        cached_response = await self._check_cached_response(cache_key)
        if cached_response:
            return cached_response

        # 초기 상태 생성
        initial_state = self._create_initial_state(user_input)

        try:
            # 워크플로우 실행
            print("[DEBUG] Executing workflow graph...")
            config = {"configurable": {"thread_id": user_input["session_id"]}}
            final_state = await self.graph.ainvoke(initial_state, config)

            # 결과 생성
            result = self._create_workflow_result(final_state)

            # 성공적인 결과 캐싱
            if result["success"] and result["response"]:
                await self._cache_workflow_result(cache_key, result)

            # 데이터셋 자동 저장 (LLM 호출이 있었을 경우)
            await self._auto_save_dataset()

            print("[DEBUG] Workflow execution completed successfully")
            return result

        except Exception as e:
            print(f"[ERROR] Workflow execution failed: {str(e)}")
            return self._create_error_result(e, initial_state)


    def _generate_cache_key(self, query: str) -> str:
        """캐시 키 생성"""
        query_normalized = query.strip().lower()
        query_hash = hashlib.md5(query_normalized.encode('utf-8')).hexdigest()
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
        """워크플로우 상태 확인"""
        health_status = {
            "workflow": "healthy",
            "components": {},
            "agents": len(self.agents),
            "timestamp": datetime.utcnow().isoformat()
        }

        # 컴포넌트 상태 확인
        try:
            health_status["components"]["query_classifier"] = "healthy"
            health_status["components"]["orchestrators"] = "healthy"
            health_status["components"]["processors"] = "healthy"
            health_status["components"]["graph"] = "healthy"
        except Exception as e:
            health_status["workflow"] = f"error: {str(e)}"

        return health_status


# 전역 워크플로우 인스턴스 (리팩토링된 버전)
multi_agent_workflow = MultiAgentWorkflow()