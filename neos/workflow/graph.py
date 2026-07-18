from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import hashlib
import logging
from langgraph.graph import StateGraph, START, END

# ★ Lazy loading agents to avoid circular imports
# Agents are imported inside _initialize_agents() method

from neos.agents.skill_based_tool_selector import SkillBasedToolSelector
from neos.utils.cache import cache_manager
from neos.utils.smart_cache_manager import smart_cache_manager
from neos.config.settings import settings
from neos.tools.tool_selector import tool_selector

from .enums import WorkflowNode, WorkflowPathway, IntentType, AutonomyLevel
from .state import AgentState, WorkflowConfig
from .harness.cache_policy import should_cache_harness_result
from .orchestrators import SearchOrchestrator, AnalysisOrchestrator, GenerationOrchestrator
from .processors import (
    ResultProcessor,
    QualityValidator,
    ResponseGenerator,
    ConversationContextProcessor,
    RefinementChecker,
    QueryRefinementAgent,
    FactCheckProcessor,
    ResearchHarnessProcessor,
    ResearchHarnessRepairProcessor,
    ResearchContinuationProcessor,
    SelfReflectionProcessor,
    HypothesisManager,
    ResearchReplanner,
)
from .utils import QueryClassifier
from .checkpointer import get_checkpointer
from .events import WorkflowEventHandler, NullEventHandler
from .routing import OrchestratorRouter, QualityRouter
from .telemetry import trace_workflow_node, add_span_event, set_span_attributes


logger = logging.getLogger(__name__)

_HARNESS_GATE_BLOCKING_VERDICTS = {"fail", "needs_repair"}

# CR-P6-11: 우선순위 라우팅 단일 테이블 — 향후 CANVAS_RENDERING 등 추가 시 여기만 수정
_PRIORITY_ROUTING_MAP: dict[str, str] = {
    IntentType.TASK_SCHEDULING.value: "task_scheduling",
}


def _resolve_autonomy_level(raw_level: Any) -> int:
    if raw_level is None:
        raw_level = settings.DEFAULT_AUTONOMY_LEVEL

    try:
        return AutonomyLevel(int(raw_level)).value
    except (TypeError, ValueError):
        return AutonomyLevel.ASSISTED.value


def _coerce_quality_score(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_gate_harness_blocked(final_state: Dict[str, Any] | None) -> bool:
    if not final_state:
        return False
    return (
        str(final_state.get("harness_mode") or "").lower() == "gate"
        and str(final_state.get("harness_verdict") or "").lower()
        in _HARNESS_GATE_BLOCKING_VERDICTS
    )


def _should_route_to_harness_repair(final_state: Dict[str, Any] | None) -> str:
    if not final_state:
        return "end"
    if str(final_state.get("harness_mode") or "").lower() != "gate":
        return "end"
    if str(final_state.get("harness_verdict") or "").lower() != "needs_repair":
        return "end"
    contract = final_state.get("harness_contract") or {}
    attempts = int(final_state.get("harness_repair_attempts") or 0)
    max_attempts = int(contract.get("max_repair_attempts") or 0)
    return "repair" if attempts < max_attempts else "end"


def _harness_blocked_message(final_state: Dict[str, Any]) -> str:
    failed = final_state.get("harness_failed_checks") or []
    failed_text = ", ".join(str(item) for item in failed) if failed else "unknown"
    return (
        "검증 중 일부 핵심 조건을 만족하지 못해 최종 보고서로 확정하지 않았습니다.\n"
        f"부족한 항목: {failed_text}\n"
        "가능한 다음 작업: 추가 검색 또는 수리 후 재검증"
    )


def _should_bypass_cache_for_mission(
    user_input: Dict[str, Any],
    autonomy_level: int,
) -> bool:
    from neos.workflow.mission.routing import has_mission_request_hint

    preferences = user_input.get("preferences") or {}
    if preferences.get("use_mission_runtime"):
        return True
    if has_mission_request_hint(user_input):
        return True
    return autonomy_level == AutonomyLevel.MANUAL.value


def _mission_validation_passed(result: Dict[str, Any]) -> bool:
    metadata = result.get("metadata") or {}
    if not metadata.get("mission_id"):
        return True
    validation_summary = metadata.get("validation_summary") or {}
    return validation_summary.get("passed") is True


def _get_priority_routing(state: AgentState) -> str | None:
    """최우선 라우팅 경로 반환. 해당 없으면 None."""
    return _PRIORITY_ROUTING_MAP.get(state.get("query_intent", ""))


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
        self.refinement_checker = RefinementChecker()
        self.query_refinement_agent = QueryRefinementAgent()
        self.conversation_context_processor = ConversationContextProcessor()
        self.query_classifier = QueryClassifier(self.config)
        self.skill_tool_selector = SkillBasedToolSelector()
        self.search_orchestrator = SearchOrchestrator(self.agents, self.config, tool_selector)
        self.analysis_orchestrator = AnalysisOrchestrator(self.agents, self.config)
        self.generation_orchestrator = GenerationOrchestrator(self.agents, self.config)
        self.result_processor = ResultProcessor()
        self.fact_check_processor = FactCheckProcessor()
        self.quality_validator = QualityValidator(self.config)
        self.research_harness_processor = ResearchHarnessProcessor()
        self.research_harness_repair_processor = ResearchHarnessRepairProcessor()
        self.response_generator = ResponseGenerator()

        from .mission.executor import MissionExecutor
        from .mission.integrator import MissionIntegrator
        from .mission.planner import MissionPlanner
        from .mission.validators import MissionValidator

        self.mission_planner = MissionPlanner()
        self.mission_executor = MissionExecutor(
            search_orchestrator=self.search_orchestrator,
            analysis_orchestrator=self.analysis_orchestrator,
            generation_orchestrator=self.generation_orchestrator,
            recursive_orchestrator=lambda: self.recursive_orchestrator,
            hyper_deep_orchestrator=lambda: self.hyper_deep_orchestrator,
        )
        self.mission_validator = MissionValidator(
            fact_check_processor=self.fact_check_processor,
            quality_validator=self.quality_validator,
        )
        self.mission_integrator = MissionIntegrator()

        # Phase 2 processors
        self.research_continuation_processor = ResearchContinuationProcessor()
        self.self_reflection_processor = SelfReflectionProcessor()

        # Phase 2 (OpenClaw Execution Approval)
        self.approval_processor = None
        if settings.EXECUTION_APPROVAL_ENABLED:
            from neos.workflow.processors.approval_processor import ApprovalProcessor
            self.approval_processor = ApprovalProcessor()
            logger.info("[MultiAgentWorkflow] ApprovalProcessor initialized (EXECUTION_APPROVAL_ENABLED)")

        # Phase 8 (OpenClaw A2UI): UIFrameGenerator (피처 플래그로 격리)
        self.ui_frame_generator = None
        if settings.A2UI_ENABLED:
            from neos.workflow.processors.ui_frame_generator import UIFrameGenerator
            self.ui_frame_generator = UIFrameGenerator()
            logger.info("[MultiAgentWorkflow] UIFrameGenerator initialized (A2UI_ENABLED)")
        self.hypothesis_manager = HypothesisManager()  # Phase 2.5
        self.research_replanner = ResearchReplanner()  # Phase 2.4

        # ROMA: Recursive Agent (피처 플래그로 격리)
        self.recursive_orchestrator = None
        if settings.RECURSIVE_AGENT_ENABLED:
            from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
            self.recursive_orchestrator = RecursiveOrchestrator(agents=self.agents)
            logger.info("[MultiAgentWorkflow] RecursiveOrchestrator initialized (ROMA enabled)")

        # HyperDeep Recursive: ROMA + HyperDeepResearchAgent 통합 (피처 플래그로 격리)
        self.hyper_deep_orchestrator = None
        if settings.HYPER_DEEP_AGENT_ENABLED:
            if getattr(settings, "RAY_ENABLED", False):
                # Ray 분산 실행 경로: HyperDeepExecutor 싱글톤 불필요
                # (HyperDeepWorkerActor가 독립 프로세스에서 HyperDeepResearchAgent 직접 보유)
                from neos.workflow.recursive.distributed_orchestrator import (
                    DistributedRecursiveOrchestrator,
                )
                self.hyper_deep_orchestrator = DistributedRecursiveOrchestrator(
                    agents=self.agents,
                    max_depth=settings.HYPER_DEEP_MAX_DEPTH,
                    budget_cap=settings.HYPER_DEEP_BUDGET_CAP,
                    max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
                    ray_enabled=True,
                    ray_pool_size=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
                )
                logger.info(
                    "[MultiAgentWorkflow] HyperDeepOrchestrator initialized with Ray "
                    f"(max_depth={settings.HYPER_DEEP_MAX_DEPTH}, "
                    f"pool_size={settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL})"
                )
            else:
                # 기존 순차 실행 경로
                from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
                from neos.workflow.hyper_deep.executor import HyperDeepExecutor
                _hd_executor = HyperDeepExecutor()
                self.hyper_deep_orchestrator = RecursiveOrchestrator(
                    agents=self.agents,
                    executor=_hd_executor,
                    max_depth=settings.HYPER_DEEP_MAX_DEPTH,
                    budget_cap=settings.HYPER_DEEP_BUDGET_CAP,
                    max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
                )
                logger.info(
                    "[MultiAgentWorkflow] HyperDeepOrchestrator initialized "
                    f"(max_depth={settings.HYPER_DEEP_MAX_DEPTH}, "
                    f"tasks_per_level={settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL})"
                )

        # 워크플로우 그래프 생성 (비동기로 초기화)
        self.graph = None
        self._graphs_by_checkpointer: dict[bool, Any] = {}
        self._graph_initialized = False
        self._graph_uses_checkpointer = False
        self._orchestrator_router = OrchestratorRouter()
        self._quality_router = QualityRouter()


    def _initialize_agents(self) -> Dict[str, Any]:
        """에이전트 초기화"""
        # Lazy import agents to avoid circular imports
        from neos.agents.search_agents import (
            KnowledgeSearchAgent,
            RealtimeInfoSearchAgent,
            RealtimeDataSearchAgent,
            MultiQuerySearchAgent,
            WebLookUpAgent,
            YouTubeSearchAgent
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

        logger.debug("Initializing agents...")

        agents = {
            # 검색 에이전트들
            "knowledge_search": KnowledgeSearchAgent(),
            "realtime_info_search": RealtimeInfoSearchAgent(),
            "realtime_data_search": RealtimeDataSearchAgent(),
            "multi_query_search": MultiQuerySearchAgent(),
            "web_lookup": WebLookUpAgent(),
            "youtube_search": YouTubeSearchAgent(),

            # 분석 에이전트들
            IntentType.DATA_ANALYSIS.value: DataAnalysisAgent(),
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
        workflow.add_node(WorkflowNode.REFINEMENT_CHECKER.value, self._check_refinement_node)
        workflow.add_node(WorkflowNode.QUERY_REFINEMENT.value, self._refine_query_node)
        workflow.add_node(WorkflowNode.RESEARCH_CONTINUATION.value, self._research_continuation_node)  # Phase 2.2
        workflow.add_node(WorkflowNode.CONVERSATION_CTX_PROC.value, self._process_conversation_context_node)
        workflow.add_node(WorkflowNode.QUERY_CLS.value, self._classify_query_node)
        workflow.add_node(WorkflowNode.SKILL_TOOL_SELECTOR.value, self._select_skills_tools_node)
        workflow.add_node(WorkflowNode.HYPOTHESIS_GENERATION.value, self._hypothesis_generation_node)  # Phase 2.5
        workflow.add_node(WorkflowNode.SEARCH_ORCHESTRATOR.value, self._orchestrate_search_node)
        workflow.add_node(WorkflowNode.HYPOTHESIS_EVALUATION.value, self._hypothesis_evaluation_node)  # Phase 2.5
        workflow.add_node(WorkflowNode.REPLANNER.value, self._replanner_node)  # Phase 2.4
        workflow.add_node(WorkflowNode.ANALYSIS_ORCHESTRATOR.value, self._orchestrate_analysis_node)
        workflow.add_node(WorkflowNode.GENERATION_ORCHESTRATOR.value, self._orchestrate_generation_node)
        workflow.add_node(WorkflowNode.RESULT_INTEGRATOR.value, self._integrate_results_node)
        workflow.add_node(WorkflowNode.FACT_CHECK.value, self._fact_check_node)
        workflow.add_node(WorkflowNode.QUALITY_VALIDATOR.value, self._validate_quality_node)
        workflow.add_node(WorkflowNode.RESEARCH_HARNESS.value, self._research_harness_node)
        workflow.add_node(
            WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
            self._research_harness_repair_node,
        )
        workflow.add_node(WorkflowNode.SELF_REFLECTION.value, self._self_reflection_node)  # Phase 2.6
        workflow.add_node(WorkflowNode.MISSION_PLANNER.value, self._mission_planner_node)
        workflow.add_node(WorkflowNode.MISSION_APPROVAL.value, self._mission_approval_node)
        workflow.add_node(WorkflowNode.MISSION_EXECUTOR.value, self._mission_executor_node)
        workflow.add_node(WorkflowNode.MISSION_VALIDATOR.value, self._mission_validator_node)
        workflow.add_node(WorkflowNode.MISSION_INTEGRATOR.value, self._mission_integrator_node)
        workflow.add_node(WorkflowNode.RESP_GENERATOR.value, self._generate_response_node)

        # ROMA: Recursive Orchestrator 노드 (피처 플래그로 격리)
        if settings.RECURSIVE_AGENT_ENABLED:
            workflow.add_node(WorkflowNode.RECURSIVE_ORCHESTRATOR.value, self._recursive_orchestrator_node)

        # HyperDeep Recursive Orchestrator 노드 (피처 플래그로 격리)
        if settings.HYPER_DEEP_AGENT_ENABLED:
            workflow.add_node(WorkflowNode.HYPER_DEEP_ORCHESTRATOR.value, self._hyper_deep_orchestrator_node)

        # Phase 3b(D23): Deep Analysis 디스패치 노드 (피처 플래그로 격리)
        if settings.DEEP_ANALYSIS_ENABLED:
            workflow.add_node(WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, self._deep_analysis_dispatch_node)

        # Phase 2 (OpenClaw Execution Approval): 민감 스킬 사용자 승인 노드
        # interrupt_before=[EXECUTION_APPROVAL]로 중단 → resume 후 이 노드 실행
        if settings.EXECUTION_APPROVAL_ENABLED:
            workflow.add_node(WorkflowNode.EXECUTION_APPROVAL.value, self._execution_approval_node)

        # Phase 4 (OpenClaw Cron): 자연어 스케줄 등록 노드
        workflow.add_node(WorkflowNode.TASK_SCHEDULING_NODE.value, self._handle_task_scheduling_node)

        # 엣지 정의
        # 1. START → refinement_checker (가장 먼저 쿼리 개선 필요 여부 체크)
        workflow.add_edge(START, WorkflowNode.REFINEMENT_CHECKER.value)

        # 2. refinement_checker → 조건부 분기 (개선 필요 여부 + continuation 체크)
        workflow.add_conditional_edges(
            WorkflowNode.REFINEMENT_CHECKER.value,
            self._should_refine_or_continue,
            {
                "refine_query": WorkflowNode.QUERY_REFINEMENT.value,
                "continue_research": WorkflowNode.RESEARCH_CONTINUATION.value,  # Phase 2.2
                "skip_refinement": WorkflowNode.CONVERSATION_CTX_PROC.value,
            }
        )

        # 3. query_refinement_agent → conversation_context_processor (개선 후 정상 흐름)
        workflow.add_edge(WorkflowNode.QUERY_REFINEMENT.value, WorkflowNode.CONVERSATION_CTX_PROC.value)

        # 3b. research_continuation → conversation_context_processor (Phase 2.2)
        workflow.add_edge(WorkflowNode.RESEARCH_CONTINUATION.value, WorkflowNode.CONVERSATION_CTX_PROC.value)

        # 4. conversation_context_processor → 조건부 분기 (히스토리 활용 여부)
        workflow.add_conditional_edges(
            WorkflowNode.CONVERSATION_CTX_PROC.value,
            self._should_process_context,
            {
                "process_context": WorkflowNode.QUERY_CLS.value,  # 히스토리 처리 완료 → 분류
                "skip_context": WorkflowNode.QUERY_CLS.value      # 히스토리 없음 → 바로 분류
            }
        )

        # 주의: conversation_context_processor 자체는 항상 실행되지만,
        # 내부에서 히스토리가 없으면 스킵하는 로직이 있음
        workflow.add_edge(WorkflowNode.QUERY_CLS.value, WorkflowNode.SKILL_TOOL_SELECTOR.value)

        # 조건부 분기: 도구/에이전트가 필요 없으면 orchestrator 건너뛰고 바로 응답 생성
        # ROMA / HyperDeep / Approval / A2UI 활성화 시 확장 경로 추가
        if (settings.RECURSIVE_AGENT_ENABLED or settings.HYPER_DEEP_AGENT_ENABLED
                or settings.DEEP_ANALYSIS_ENABLED
                or settings.EXECUTION_APPROVAL_ENABLED or settings.A2UI_ENABLED):
            _routing_map = {
                WorkflowPathway.SKIP_ORCHESTRATORS.value: WorkflowNode.RESP_GENERATOR.value,
                WorkflowPathway.USE_ORCHESTRATORS.value: WorkflowNode.HYPOTHESIS_GENERATION.value,
                "mission": WorkflowNode.MISSION_PLANNER.value,
            }
            if settings.RECURSIVE_AGENT_ENABLED:
                _routing_map["recursive"] = WorkflowNode.RECURSIVE_ORCHESTRATOR.value
            if settings.HYPER_DEEP_AGENT_ENABLED:
                _routing_map["hyper_deep"] = WorkflowNode.HYPER_DEEP_ORCHESTRATOR.value
            if settings.DEEP_ANALYSIS_ENABLED:
                _routing_map["deep_analysis"] = WorkflowNode.DEEP_ANALYSIS_DISPATCH.value
            # Phase 2: 승인 대기 경로 (최우선 — _should_use_recursive_agent에서 먼저 체크)
            if settings.EXECUTION_APPROVAL_ENABLED:
                _routing_map["needs_approval"] = WorkflowNode.EXECUTION_APPROVAL.value
            # Phase 4: 스케줄 등록 경로
            _routing_map["task_scheduling"] = WorkflowNode.TASK_SCHEDULING_NODE.value
            # Phase 8: A2UI — UI 폼 생성 단락 경로
            if settings.A2UI_ENABLED:
                _routing_map["ui_frame"] = WorkflowNode.UI_FRAME_GENERATOR.value

            workflow.add_conditional_edges(
                WorkflowNode.SKILL_TOOL_SELECTOR.value,
                self._route_after_skill_tool_selector,
                _routing_map,
            )
            if settings.RECURSIVE_AGENT_ENABLED:
                # RECURSIVE_ORCHESTRATOR → RESULT_INTEGRATOR (결과 통합 후 정상 파이프라인 합류)
                workflow.add_edge(WorkflowNode.RECURSIVE_ORCHESTRATOR.value, WorkflowNode.RESULT_INTEGRATOR.value)
            if settings.HYPER_DEEP_AGENT_ENABLED:
                # HYPER_DEEP_ORCHESTRATOR → RESULT_INTEGRATOR (결과 통합 후 정상 파이프라인 합류)
                workflow.add_edge(WorkflowNode.HYPER_DEEP_ORCHESTRATOR.value, WorkflowNode.RESULT_INTEGRATOR.value)
            if settings.DEEP_ANALYSIS_ENABLED:
                # 디스패치 노드는 END로 단락한다 — 챗 턴은 job 핸들을 낸 뒤
                # 즉시 끝나야 하며(AC2), 후속 노드가 기다릴 결과가 없다.
                workflow.add_edge(WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, END)
            # Phase 8: UI_FRAME_GENERATOR 노드 등록 + END 단락 경로
            if settings.A2UI_ENABLED:
                workflow.add_node(WorkflowNode.UI_FRAME_GENERATOR.value, self._ui_frame_generator_node)
                workflow.add_edge(WorkflowNode.UI_FRAME_GENERATOR.value, END)
        else:
            # A2UI_ENABLED에 따라 라우팅 맵과 노드 등록을 동시에 조건부 처리
            # (노드 미등록 상태에서 라우팅 맵에 키만 있으면 LangGraph 경고 발생)
            _else_routing = {
                WorkflowPathway.SKIP_ORCHESTRATORS.value: WorkflowNode.RESP_GENERATOR.value,
                WorkflowPathway.USE_ORCHESTRATORS.value: WorkflowNode.HYPOTHESIS_GENERATION.value,
                "mission": WorkflowNode.MISSION_PLANNER.value,
                "task_scheduling": WorkflowNode.TASK_SCHEDULING_NODE.value,
            }
            if settings.A2UI_ENABLED:
                _else_routing["ui_frame"] = WorkflowNode.UI_FRAME_GENERATOR.value
            workflow.add_conditional_edges(
                WorkflowNode.SKILL_TOOL_SELECTOR.value,
                self._route_after_skill_tool_selector,
                _else_routing,
            )
            if settings.A2UI_ENABLED:
                workflow.add_node(WorkflowNode.UI_FRAME_GENERATOR.value, self._ui_frame_generator_node)
                workflow.add_edge(WorkflowNode.UI_FRAME_GENERATOR.value, END)

        # Phase 4 (OpenClaw Cron): TASK_SCHEDULING_NODE → 바로 응답 생성
        workflow.add_edge(WorkflowNode.TASK_SCHEDULING_NODE.value, WorkflowNode.RESP_GENERATOR.value)

        # Mission Runtime: plan -> optional approval -> serial executor -> validators -> response
        workflow.add_conditional_edges(
            WorkflowNode.MISSION_PLANNER.value,
            self._should_continue_after_mission_planner,
            {
                "approval_unavailable": WorkflowNode.RESP_GENERATOR.value,
                "needs_approval": WorkflowNode.MISSION_APPROVAL.value,
                "execute": WorkflowNode.MISSION_EXECUTOR.value,
            },
        )
        workflow.add_conditional_edges(
            WorkflowNode.MISSION_APPROVAL.value,
            self._should_continue_after_approval,
            {
                "approved": WorkflowNode.MISSION_EXECUTOR.value,
                "rejected": WorkflowNode.RESP_GENERATOR.value,
            },
        )
        workflow.add_edge(WorkflowNode.MISSION_EXECUTOR.value, WorkflowNode.MISSION_VALIDATOR.value)
        workflow.add_edge(WorkflowNode.MISSION_VALIDATOR.value, WorkflowNode.MISSION_INTEGRATOR.value)
        workflow.add_edge(WorkflowNode.MISSION_INTEGRATOR.value, WorkflowNode.RESP_GENERATOR.value)

        # Phase 2 (OpenClaw Execution Approval): EXECUTION_APPROVAL → 분기
        # approved → 오케스트레이터 경로, rejected → 응답 생성으로 바로 이동
        if settings.EXECUTION_APPROVAL_ENABLED:
            workflow.add_conditional_edges(
                WorkflowNode.EXECUTION_APPROVAL.value,
                self._should_continue_after_approval,
                {
                    "approved": WorkflowNode.HYPOTHESIS_GENERATION.value,
                    "rejected": WorkflowNode.RESP_GENERATOR.value,
                },
            )

        # Phase 2.5: HYPOTHESIS_GENERATION → SEARCH → HYPOTHESIS_EVALUATION → ANALYSIS
        workflow.add_edge(WorkflowNode.HYPOTHESIS_GENERATION.value, WorkflowNode.SEARCH_ORCHESTRATOR.value)
        workflow.add_edge(WorkflowNode.SEARCH_ORCHESTRATOR.value, WorkflowNode.HYPOTHESIS_EVALUATION.value)
        # Phase 2.4: HYPOTHESIS_EVALUATION → 조건부 replanning
        workflow.add_conditional_edges(
            WorkflowNode.HYPOTHESIS_EVALUATION.value,
            self._should_replan,
            {
                "replan": WorkflowNode.REPLANNER.value,
                "skip_replan": WorkflowNode.ANALYSIS_ORCHESTRATOR.value,
            }
        )

        # Phase 2.4: REPLANNER → 추가 검색 필요 시 loop back, 아니면 진행
        workflow.add_conditional_edges(
            WorkflowNode.REPLANNER.value,
            self._should_continue_research,
            {
                "continue_search": WorkflowNode.HYPOTHESIS_GENERATION.value,  # loop back
                "proceed": WorkflowNode.ANALYSIS_ORCHESTRATOR.value,
            }
        )
        workflow.add_edge(WorkflowNode.ANALYSIS_ORCHESTRATOR.value, WorkflowNode.GENERATION_ORCHESTRATOR.value)
        workflow.add_edge(WorkflowNode.GENERATION_ORCHESTRATOR.value, WorkflowNode.RESULT_INTEGRATOR.value)
        workflow.add_edge(WorkflowNode.RESULT_INTEGRATOR.value, WorkflowNode.FACT_CHECK.value)
        workflow.add_edge(WorkflowNode.FACT_CHECK.value, WorkflowNode.QUALITY_VALIDATOR.value)

        # 조건부 엣지 (품질 검증 결과에 따라)
        workflow.add_conditional_edges(
            WorkflowNode.QUALITY_VALIDATOR.value,
            self._should_regenerate,
            {
                WorkflowPathway.REGENERATE.value: WorkflowNode.HYPOTHESIS_GENERATION.value,  # 품질이 낮으면 가설 생성부터 다시
                WorkflowPathway.PROCEED.value: WorkflowNode.SELF_REFLECTION.value,
            }
        )

        # Phase 2.6: self_reflection → response_generator
        workflow.add_edge(WorkflowNode.SELF_REFLECTION.value, WorkflowNode.RESP_GENERATOR.value)

        workflow.add_edge(WorkflowNode.RESP_GENERATOR.value, WorkflowNode.RESEARCH_HARNESS.value)
        workflow.add_conditional_edges(
            WorkflowNode.RESEARCH_HARNESS.value,
            _should_route_to_harness_repair,
            {
                "repair": WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
                "end": END,
            },
        )
        workflow.add_edge(
            WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
            WorkflowNode.RESEARCH_HARNESS.value,
        )

        # Conditionally use checkpointer
        if use_checkpointer:
            checkpointer = await get_checkpointer()
            logger.debug("[WorkflowGraph] Created with PostgreSQL checkpointer for horizontal scaling")
            # Phase 2 (OpenClaw Execution Approval): interrupt_before는 checkpointer 경로에만 적용
            # stateless 경로(use_checkpointer=False)에서는 interrupt가 동작하지 않으므로 제외
            interrupt_nodes = (
                [
                    WorkflowNode.EXECUTION_APPROVAL.value,
                    WorkflowNode.MISSION_APPROVAL.value,
                ]
                if settings.EXECUTION_APPROVAL_ENABLED
                else []
            )
            return workflow.compile(checkpointer=checkpointer, interrupt_before=interrupt_nodes)
        else:
            logger.debug("[WorkflowGraph] Created without checkpointer (stateless mode)")
            return workflow.compile()


    async def _ensure_graph_initialized(self, use_checkpointer: bool = True):
        """
        Ensure graph is initialized before use.

        Args:
            use_checkpointer: Whether to use checkpointer for state persistence
        """
        if (
            self._graph_initialized
            and self.graph is not None
            and self._graph_uses_checkpointer == use_checkpointer
        ):
            self._graphs_by_checkpointer.setdefault(use_checkpointer, self.graph)
            return

        if use_checkpointer not in self._graphs_by_checkpointer:
            self._graphs_by_checkpointer[use_checkpointer] = (
                await self._create_workflow_graph(use_checkpointer=use_checkpointer)
            )

        self.graph = self._graphs_by_checkpointer[use_checkpointer]
        self._graph_initialized = True
        self._graph_uses_checkpointer = use_checkpointer


    async def _check_refinement_node(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 개선 필요 여부 체크 노드"""
        return await self.refinement_checker.check(state)

    async def _refine_query_node(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 개선 노드"""
        return await self.query_refinement_agent.refine(state)

    async def _research_continuation_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2.2: 후속 연구 컨텍스트 로드 노드"""
        return await self.research_continuation_processor.process(state)

    async def _self_reflection_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2.6: Self-reflection 노드"""
        return await self.self_reflection_processor.reflect(state)

    async def _hypothesis_generation_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2.5: 검색 전 경쟁 가설 생성 (DEEP_RESEARCH/COMPLEX_ANALYSIS + high complexity만)"""
        intent = state.get("query_intent", "")
        classification = state.get("query_classification") or {}
        complexity = classification.get("complexity_score", 0.0)

        if intent not in (IntentType.DEEP_RESEARCH.value, IntentType.COMPLEX_ANALYSIS.value):
            return state
        if complexity < 0.6:
            return state

        hypotheses = await self.hypothesis_manager.generate_hypotheses(
            query=state.get("original_query", ""),
            classification=classification,
        )
        logger.info(f"[Hypothesis] Generated {len(hypotheses)} hypotheses")
        return {"hypotheses": hypotheses}

    async def _hypothesis_evaluation_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2.5: 검색 후 가설 평가 및 종합"""
        hypotheses = state.get("hypotheses", [])
        if not hypotheses:
            return state

        search_results = state.get("search_results", [])
        evaluation = await self.hypothesis_manager.evaluate_hypotheses(
            hypotheses=hypotheses,
            search_results=search_results,
        )
        logger.info(f"[Hypothesis] Evaluation complete: strongest={evaluation.get('strongest')}")
        return {"hypothesis_results": evaluation}

    async def _replanner_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2.4: 중간 결과 기반 적응형 연구 재계획"""
        return await self.research_replanner.evaluate_and_replan(state)

    async def _classify_query_node(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 노드"""
        # refined_query가 있으면 그것을 사용, 없으면 original_query 사용
        query_to_classify = state.get("refined_query", state["original_query"])

        # 분류 시 refined_query를 사용하도록 임시로 변경
        original_backup = state["original_query"]
        state["original_query"] = query_to_classify

        result = await self.query_classifier.classify_query(state)

        # original_query 복원 (메타데이터 유지)
        state["original_query"] = original_backup

        # Phase 4.7: Research Template 자동 선택
        # 사용자가 template_id를 이미 지정하지 않았고, API에서 전달하지 않은 경우에만 자동 선택
        if not state.get("template_id"):
            await self._try_select_template(state, query_to_classify, result)

        return result

    async def _try_select_template(
        self, state: AgentState, query: str, classification_result: Dict[str, Any]
    ) -> None:
        """Phase 4.7: 쿼리에 맞는 연구 템플릿을 자동 선택하여 state에 반영"""
        try:
            from neos.templates.template_selector import TemplateSelector

            selector = TemplateSelector()
            intent = classification_result.get("query_intent")
            match = await selector.select(query=query, intent=intent)

            if match:
                template = match["template"]
                state["template_id"] = template.template_id
                state["template_config"] = {
                    "workflow_overrides": template.workflow_overrides,
                    "required_agents": template.required_agents,
                    "recommended_skills": template.recommended_skills,
                    "research_guidance": template.research_guidance,
                    "output_format": template.output_format,
                    "params": match.get("params", {}),
                    "confidence": match.get("confidence", 0.0),
                }

                # 템플릿의 required_agents를 기존 에이전트 목록에 merge
                existing_agents = state.get("required_agents") or []
                for agent in template.required_agents:
                    if agent not in existing_agents:
                        existing_agents.append(agent)
                state["required_agents"] = existing_agents

                logger.info(
                    f"[TemplateSelector] Applied template '{template.name}' "
                    f"(confidence={match['confidence']:.2f})"
                )
        except Exception as e:
            logger.debug(f"[TemplateSelector] Template selection skipped: {e}")

    async def _select_skills_tools_node(self, state: AgentState) -> Dict[str, Any]:
        """Skill and Tool selection 노드"""
        logger.debug("[SkillToolSelector] Executing skill/tool selection")

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
                "requires_analysis": IntentType.DATA_ANALYSIS.value in state.get("required_agents", []),
                "requires_search": any(
                    agent in state.get("required_agents", [])
                    for agent in [
                        "knowledge_search", "realtime_info_search", "multi_query_search",
                    ]
                ),
                "autonomy_level": state.get("autonomy_level"),
            }

            # Call skill/tool selector
            selection = await self.skill_tool_selector.select_skills_and_tools(
                query=query,
                context=selection_context,
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )

            logger.debug(f"[SkillToolSelector] Selected {len(selection.selected_skills)} skills: {selection.selected_skills}")
            logger.debug(f"[SkillToolSelector] Selected {len(selection.selected_tools)} tools: {selection.selected_tools}")

            base_result = {
                "selected_skills": selection.selected_skills,
                "selected_tools": selection.selected_tools,
                "selection_reasoning": selection.reasoning,
            }

            from neos.workflow.mission.routing import should_use_mission_runtime

            candidate_state = {**state, **base_result}
            if should_use_mission_runtime(candidate_state):
                return base_result

            # Phase 2 (OpenClaw Execution Approval): 민감 스킬 allowlist 체크
            # checkpointed 경로에서만 유효 — stateless 경로에서는 interrupt_before가 동작하지 않으므로
            # approval 로직을 수행하면 approval_decision=None 상태로 EXECUTION_APPROVAL 노드가 즉시
            # 실행되어 "승인 처리 중 예기치 않은 상태" 오류 메시지로 워크플로우가 종료된다.
            if settings.EXECUTION_APPROVAL_ENABLED and self._graph_uses_checkpointer:
                from neos.workflow.autonomy.middleware import get_policy_from_state

                approval_required_skills = (
                    get_policy_from_state(state).get_approval_required_actions(
                        required_agents=state.get("required_agents", []),
                        selected_skills=selection.selected_skills,
                        selected_tools=selection.selected_tools,
                    )
                )
                approval_skills = approval_required_skills
                if approval_skills:
                    # DB allowlist 조회 — allowlist에 있으면 자동 승인
                    is_allowlisted = await self._check_approval_allowlist(user_id, approval_skills)
                    if not is_allowlisted:
                        import uuid as _uuid
                        from datetime import datetime as _dt
                        pending = [
                            {
                                "request_id": str(_uuid.uuid4()),
                                "skill_name": s,
                                "params": {},
                                "timeout_seconds": settings.APPROVAL_TIMEOUT_SECONDS,
                                "requested_at": _dt.utcnow().isoformat(),
                            }
                            for s in approval_skills
                        ]
                        logger.info(
                            f"[ApprovalCheck] Skills require approval: {approval_skills} "
                            f"for user={user_id}. Setting pending_approvals."
                        )
                        asyncio.create_task(
                            _register_pending_approvals_db(
                                pending,
                                user_id,
                                session_id,
                            )
                        )
                        return {
                            **base_result,
                            "pending_approvals": pending,
                            "approval_decision": None,
                        }

            return base_result

        except Exception as e:
            import traceback
            logger.error(f"[SkillToolSelector] Selection failed: {e}\n{traceback.format_exc()}")
            # Return empty selections on error
            return {
                "selected_skills": [],
                "selected_tools": [],
                "selection_reasoning": f"Selection failed: {str(e)}"
            }

    async def _process_conversation_context_node(self, state: AgentState) -> Dict[str, Any]:
        """대화 컨텍스트 처리 노드"""
        return await self.conversation_context_processor.process(state)

    async def _execution_approval_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 2 (OpenClaw Execution Approval): 실행 승인 노드

        interrupt_before에 의해 중단된 후 resume 시 실행된다.
        state["approval_decision"]에 사용자 결정("approved"|"rejected")이 담겨 있다.
        """
        if self.approval_processor is None:
            logger.error("[ExecutionApprovalNode] ApprovalProcessor is not initialized")
            return {"pending_approvals": [], "approval_decision": None}
        return await self.approval_processor.process(state)

    async def _mission_planner_node(self, state: AgentState) -> Dict[str, Any]:
        """Mission Runtime: MissionPlan과 ValidationContract 생성."""
        result = await self.mission_planner.plan(state)
        if result.get("pending_approvals") and not self._mission_approval_available():
            result.update(
                {
                    "pending_approvals": [],
                    "approval_decision": None,
                    "approval_outcome": "rejected",
                    "mission_status": "approval_unavailable",
                    "final_response": (
                        "Manual mission 승인을 처리할 수 없습니다. "
                        "EXECUTION_APPROVAL_ENABLED와 checkpointer가 활성화되어야 합니다."
                    ),
                }
            )
        return result

    def _mission_approval_available(self) -> bool:
        return bool(
            settings.EXECUTION_APPROVAL_ENABLED
            and self._graph_uses_checkpointer
            and self.approval_processor is not None
        )

    async def _mission_approval_node(self, state: AgentState) -> Dict[str, Any]:
        """Mission Runtime: 실행 전 mission-level 승인 처리."""
        if self.approval_processor is None:
            logger.error("[MissionApprovalNode] ApprovalProcessor is not initialized")
            return {
                "pending_approvals": [],
                "approval_decision": None,
                "approval_outcome": "rejected",
            }
        return await self.approval_processor.process(state)

    async def _mission_executor_node(self, state: AgentState) -> Dict[str, Any]:
        """Mission Runtime: 기존 orchestrator를 task wrapper로 순차 실행."""
        return await self.mission_executor.execute(state)

    async def _mission_validator_node(self, state: AgentState) -> Dict[str, Any]:
        """Mission Runtime: ValidationContract 기반 검증."""
        return await self.mission_validator.validate(state)

    async def _mission_integrator_node(self, state: AgentState) -> Dict[str, Any]:
        """Mission Runtime: mission 결과 메타데이터 통합."""
        return await self.mission_integrator.integrate(state)

    async def _ui_frame_generator_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 8 (OpenClaw A2UI): UIFrame 생성 노드 래퍼.

        QueryClassifier가 needs_ui=True로 표시한 쿼리에 대해 동적 UI 컴포넌트를 생성한다.
        UI_FRAME_GENERATOR → END 단락 경로 (research 파이프라인 우회).
        """
        if self.ui_frame_generator is None:
            logger.error("[UIFrameGeneratorNode] UIFrameGenerator is not initialized")
            return {"needs_ui": False}
        return await self.ui_frame_generator.generate(state)

    async def _handle_task_scheduling_node(self, state: AgentState) -> Dict[str, Any]:
        """Phase 4 (OpenClaw Cron): 자연어 스케줄 등록 노드.

        IntentType.TASK_SCHEDULING으로 분류된 쿼리를 CronSkill로 위임한다.
        결과(final_response)를 설정하면 RESP_GENERATOR가 그대로 반환한다.
        """
        from neos.skills.builtin.cron.skill import CronSkill

        query = state.get("original_query", "")
        user_id = state.get("user_id", "")
        channel_type = state.get("channel_type", "api") or "api"
        channel_id = state.get("channel_id")

        logger.info("[TaskScheduling] Handling schedule registration: query=%s", query[:80])

        try:
            cron_skill = CronSkill()
            result = await cron_skill.execute(
                query=query,
                user_id=user_id,
                channel_type=channel_type,
                channel_id=channel_id,
            )
            if result.success:
                final_response = result.data.get("message", "스케줄이 등록되었습니다.")
            else:
                final_response = f"스케줄 등록에 실패했습니다: {result.error}"
        except Exception as exc:
            logger.error("[TaskScheduling] CronSkill execution failed: %s", exc, exc_info=True)
            final_response = "스케줄 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

        return {"final_response": final_response}

    def _should_continue_after_approval(self, state: AgentState) -> str:
        """EXECUTION_APPROVAL 노드 이후 라우팅 함수.

        approval_processor가 설정한 approval_outcome 전용 필드를 사용한다.
        이전 세션의 final_response 잔류값에 의한 오라우팅을 방지한다.

        Returns:
            "approved": 오케스트레이터 경로 (HYPOTHESIS_GENERATION)
            "rejected": 응답 생성 (RESP_GENERATOR)
        """
        return state.get("approval_outcome", "rejected")

    async def _check_approval_allowlist(self, user_id: str, skill_names: list) -> bool:
        """DB에서 user_id의 skill_names 전체가 allowlist에 있는지 확인한다.

        Args:
            user_id: 사용자 ID
            skill_names: 확인할 스킬 이름 목록

        Returns:
            True: 모든 스킬이 allowlist에 있어 자동 승인 가능
            False: 하나라도 없으면 사용자 승인 필요
        """
        if not skill_names:
            return True
        try:
            from neos.database.connection import db_manager
            placeholders = ", ".join(f"${i+2}" for i in range(len(skill_names)))
            sql = f"""
                SELECT COUNT(*) AS count FROM tool_approval_allowlist
                WHERE user_id = $1
                  AND skill_name IN ({placeholders})
                  AND auto_approved = TRUE
            """
            row = await db_manager.fetch_one(sql, user_id, *skill_names)
            count = int(row["count"]) if row else 0
            return count >= len(skill_names)
        except Exception as e:
            logger.debug(f"[ApprovalCheck] Allowlist DB query failed: {e} — requiring approval")
            return False

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

    async def _fact_check_node(self, state: AgentState) -> Dict[str, Any]:
        """Fact-check 노드 (조건부 실행)"""
        return await self.fact_check_processor.check_facts(state)

    async def _validate_quality_node(self, state: AgentState) -> Dict[str, Any]:
        """품질 검증 노드"""
        return await self.quality_validator.validate_quality(state)

    async def _research_harness_node(self, state: AgentState) -> Dict[str, Any]:
        """Research harness validation node."""
        updates = await self.research_harness_processor.process(state)
        return {**state, **updates}

    async def _research_harness_repair_node(self, state: AgentState) -> Dict[str, Any]:
        """Plan and execute bounded repair work before harness revalidation."""
        updates = await self.research_harness_repair_processor.process(state)
        repaired_state = {**state, **updates}

        if not updates.get("harness_repair_plan"):
            return repaired_state

        plan = updates["harness_repair_plan"]
        action_types = {action.get("action_type") for action in plan.get("actions", [])}
        repaired_state = {
            **repaired_state,
            "final_response": None,
            "response_metadata": None,
        }

        if action_types & {
            "request_more_sources",
            "search_independent_domains",
            "date_constrained_freshness_search",
        }:
            repaired_state = await self.search_orchestrator.orchestrate(repaired_state)

        repaired_state = await self.result_processor.integrate_results(repaired_state)
        repaired_state = await self.response_generator.generate_response(repaired_state)
        return repaired_state

    async def _generate_response_node(self, state: AgentState) -> Dict[str, Any]:
        """응답 생성 노드"""
        return await self.response_generator.generate_response(state)

    async def _recursive_orchestrator_node(self, state: AgentState) -> Dict[str, Any]:
        """ROMA: 재귀 오케스트레이터 노드"""
        if self.recursive_orchestrator is None:
            logger.error("[RecursiveOrchestratorNode] RecursiveOrchestrator is not initialized")
            return {"final_response": "재귀 에이전트가 초기화되지 않았습니다."}
        return await self.recursive_orchestrator.execute(state)

    async def _hyper_deep_orchestrator_node(self, state: AgentState) -> Dict[str, Any]:
        """HyperDeep Recursive: ROMA + HyperDeepResearchAgent 오케스트레이터 노드"""
        if self.hyper_deep_orchestrator is None:
            logger.error("[HyperDeepOrchestratorNode] HyperDeepOrchestrator is not initialized")
            return {"final_response": "HyperDeep 재귀 에이전트가 초기화되지 않았습니다."}
        logger.info(
            f"[HyperDeepOrchestratorNode] Starting for: "
            f"{state.get('original_query', '')[:60]}"
        )
        return await self.hyper_deep_orchestrator.execute(state)

    async def _deep_analysis_dispatch_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3b(D23): 심층 분석을 job으로 제출하고 즉시 반환한다.

        D18의 블로킹 완주 노드를 대체한다. 세 예산을 나란히 놓으면 프론트
        maxDuration 60s < 노드 캡 300s < dig 하나의 wall_clock_cap 600s이므로,
        **가장 작은 예산이 클라이언트 쪽에 있다** -- 라운드를 여러 번 도는 run은
        어떤 동기 요청 예산에도 애초에 맞지 않는다. 노드 레벨 캡(9763eb5)은
        호출자가 떠난 뒤 자원을 붙드는 것만 막았을 뿐 사용자가 결과를 받게 하지
        못했다. 여기서 캡이 사라지는 것은 퇴행이 아니라, 붙들 자원이 없어진
        것이다(스펙 5.2).

        진행 상황과 최종 리포트는 `events_url`의 전용 SSE 스트림이 전달한다 --
        챗과 전용 API가 **같은 이벤트 스트림 계약**을 쓴다(AC4).
        """
        import uuid

        from neos.config.settings import settings
        from neos.database.connection import db_manager
        from neos.tasks.deep_analysis_job_task import submit_deep_analysis_job
        from neos.workflow.deep_analysis.ledger import create_run

        query = state.get("refined_query") or state.get("original_query", "")
        profile = "default"
        conversation_id = state.get("conversation_id")
        # 대화에 묶인 run만 어시스턴트 메시지를 예약한다. job이 완료되면
        # 실행자 계층(neos/tasks/deep_analysis_job_task.py)이 이 ID로 리포트를
        # 영속화하므로, 프론트가 그 순간 접속해 있지 않아도 대화에 남는다.
        assistant_message_id = str(uuid.uuid4()) if conversation_id else None

        try:
            async with await db_manager.get_session() as session:
                run_id = await create_run(
                    session,
                    query,
                    profile,
                    user_id=state.get("user_id") or None,
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                )
                # 커밋이 필수다 -- job이 다른 태스크/프로세스에서 이 run을 읽는다.
                await session.commit()

            executor = submit_deep_analysis_job(run_id, query, profile)
        except Exception as exc:
            logger.error(f"[DeepAnalysisDispatchNode] submission failed: {exc}")
            return {
                "final_response": "심층 분석을 시작하지 못했습니다.",
                "deep_analysis_run_id": None,
            }

        events_url = f"{settings.API_V1_PREFIX}/deep-analysis/{run_id}/events"
        event_handler = state.get("_event_handler")
        if event_handler and hasattr(event_handler, "on_deep_analysis_started"):
            await event_handler.on_deep_analysis_started(
                run_id=run_id,
                events_url=events_url,
                assistant_message_id=assistant_message_id,
            )

        logger.info(
            f"[DeepAnalysisDispatchNode] run {run_id} submitted via {executor}"
        )
        return {
            "final_response": (
                "심층 분석을 시작했습니다. 진행 상황과 최종 리포트는 "
                "분석이 끝나는 대로 이 대화에 표시됩니다."
            ),
            "deep_analysis_run_id": run_id,
            "execution_steps": state.get("execution_steps", [])
            + [
                {
                    "step": "deep_analysis_dispatch",
                    "result": f"run {run_id} submitted via {executor}",
                }
            ],
        }


    def _should_use_recursive_agent(self, state: AgentState) -> str:
        """ROMA / HyperDeep: 재귀 에이전트 사용 여부 판단 라우팅 함수.

        우선순위:
        1. HYPER_DEEP_AGENT_ENABLED → hyper_deep_research intent 또는 높은 복잡도
        2. RECURSIVE_AGENT_ENABLED → recursive_research intent 또는 높은 복잡도
        3. 기존 로직 (use_orchestrators / skip_orchestrators)

        Returns:
            "hyper_deep": HYPER_DEEP_ORCHESTRATOR로 라우팅
            "recursive": RECURSIVE_ORCHESTRATOR로 라우팅
            WorkflowPathway.USE_ORCHESTRATORS.value: 기존 오케스트레이터 경로
            WorkflowPathway.SKIP_ORCHESTRATORS.value: 바로 응답 생성
        """
        return self._orchestrator_router.route(state)

    def _route_after_skill_tool_selector(self, state: AgentState) -> str:
        """SkillToolSelector 이후 mission/runtime/legacy 경로를 결정한다."""
        legacy_route = self._orchestrator_router.route(state)
        if legacy_route in {"needs_approval", "task_scheduling", "ui_frame"}:
            return legacy_route

        mission_route = self._should_use_mission_runtime(state)
        if mission_route == "mission":
            return mission_route
        return legacy_route

    def _should_use_mission_runtime(self, state: AgentState) -> str:
        """Mission Runtime 후보면 mission branch로 보낸다."""
        from neos.workflow.mission import routing as mission_routing

        return (
            "mission"
            if mission_routing.should_use_mission_runtime(state)
            else "legacy"
        )

    def _should_continue_after_mission_planner(self, state: AgentState) -> str:
        """MissionPlanner 이후 승인 필요 여부를 판단한다."""
        if state.get("mission_status") == "approval_unavailable":
            return "approval_unavailable"
        if state.get("pending_approvals") and state.get("approval_decision") is None:
            return "needs_approval"
        return "execute"

    def _should_refine_query(self, state: AgentState) -> str:
        """
        쿼리 개선 필요 여부 결정

        RefinementChecker가 개선이 필요하다고 판단하면 query_refinement_agent로,
        필요 없으면 conversation_context_processor로 이동
        """
        needs_refinement = state.get("needs_refinement", False)

        if needs_refinement:
            print(f"[DEBUG] Query refinement needed: {state.get('refinement_reasons', [])}")
            return "refine_query"

        print("[DEBUG] Query refinement not needed, skipping")
        return "skip_refinement"

    def _should_refine_or_continue(self, state: AgentState) -> str:
        """Phase 2.2: 쿼리 개선 / 후속 연구 / 일반 진행 결정

        is_continuation=True이면 research_continuation 노드로 라우팅.
        """
        return self._quality_router.should_refine_or_continue(state)

    def _should_process_context(self, state: AgentState) -> str:
        """
        대화 컨텍스트 처리 여부 결정

        이 함수는 이제 conversation_context_processor 내부에서 처리되므로
        항상 query_classifier로 이동
        """
        # conversation_context_processor는 이미 실행됨
        # 내부에서 히스토리 여부를 확인하고 처리
        return self._quality_router.should_process_context(state)

    def _should_replan(self, state: AgentState) -> str:
        """Phase 2.4: replanning 필요 여부 결정

        조건: sub_topics 존재 + 검색 결과 < 10 + replan_count < 2
        """
        return self._quality_router.should_replan(state)

    def _should_continue_research(self, state: AgentState) -> str:
        """Phase 2.4: replanning 후 추가 검색 필요 여부 결정"""
        return self._quality_router.should_continue_research(state)

    def _should_regenerate(self, state: AgentState) -> str:
        """재생성 여부 결정"""
        return self._quality_router.should_regenerate(state, self.quality_validator)

    def _should_skip_orchestrators(self, state: AgentState) -> str:
        """
        Orchestrator들을 건너뛰고 바로 응답 생성할지 결정

        개선된 로직:
        1. 기본 조건: required_agents와 selected_tools가 비어있음
        2. 추가 검증: 의도, 복잡도, 쿼리 내용 분석
        3. 안전장치: 특정 조건에서는 항상 orchestrator 사용

        Returns:
            `skip_orchestrators`: response_generator로 직접 이동
            `use_orchestrators`: search_orchestrator로 이동하여 정상 파이프라인 실행
        """
        return self._orchestrator_router.base_route(state)

    def _is_question_query(self, query: str) -> bool:
        """
        질문 형태인지 판단

        TODO: 비즈니스 로직을 개선하세요

        현재 구현:
        - "?" 포함 여부
        - 의문사 포함 여부 (어디, 언제, 누가, 무엇, 왜, 어떻게)
        """
        return self._orchestrator_router.is_question_query(query)

    def _requires_search_keywords(self, query: str) -> bool:
        """
        검색이 필요한 키워드가 있는지 판단

        TODO: 도메인에 맞는 키워드를 추가하세요

        현재 구현:
        - 실시간/최신 정보 키워드
        - 비교/분석 키워드
        - 수치/데이터 키워드
        """
        return self._orchestrator_router.requires_search_keywords(query)


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
        # OpenTelemetry: 전체 워크플로우 실행 추적 (Phase 3)
        workflow_id = user_input.get("session_id", "unknown")
        query = user_input["query"]

        with trace_workflow_node(
            "workflow_execution",
            workflow_id=workflow_id,
            query_length=len(query),
            use_checkpointer=use_checkpointer
        ) as span:
            # Null Object Pattern: event_handler가 없으면 기본 핸들러 사용
            if event_handler is None:
                event_handler = NullEventHandler()

            user_id = user_input.get("user_id")
            logger.debug(f"[ExecuteWorkflow] Starting for query: {query[:50]}...")

            # 워크플로우 시작 이벤트
            await event_handler.on_workflow_start(user_input)

            # Tracing: 워크플로우 시작 이벤트 기록
            add_span_event(span, "workflow_started", {"query_preview": query[:100]})
            autonomy_level = _resolve_autonomy_level(user_input.get("autonomy_level"))
            bypass_cache = bool(user_input.get("bypass_cache", False)) or (
                _should_bypass_cache_for_mission(user_input, autonomy_level)
            )
            cache_key = self._generate_cache_key(
                query,
                user_id,
                autonomy_level=autonomy_level,
            )

            # 1. 스마트 캐시 확인 (활성화된 경우)
            if bypass_cache:
                add_span_event(span, "cache_bypassed")
                set_span_attributes(span, {"cache.bypassed": True})
            elif settings.SMART_CACHE_ENABLED:
                add_span_event(span, "checking_smart_cache")
                smart_cache_result = await self._check_smart_cache(
                    query,
                    user_id,
                    autonomy_level=autonomy_level,
                )
                if smart_cache_result:
                    # 캐시 히트 시에도 완료 이벤트 발행
                    add_span_event(span, "smart_cache_hit")
                    set_span_attributes(span, {"cache.hit": True, "cache.type": "smart_cache"})
                    await event_handler.on_workflow_complete(smart_cache_result)
                    return smart_cache_result
                add_span_event(span, "smart_cache_miss")

            # 2. 기존 Redis 캐시 확인 (폴백)
            if not bypass_cache:
                add_span_event(span, "checking_redis_cache")
                cached_response = await self._check_cached_response(cache_key)
                if cached_response:
                    add_span_event(span, "redis_cache_hit")
                    set_span_attributes(span, {"cache.hit": True, "cache.type": "redis"})
                    await event_handler.on_workflow_complete(cached_response)
                    return cached_response
                add_span_event(span, "redis_cache_miss")
            set_span_attributes(span, {"cache.hit": False})

            # Ensure graph is initialized only after cache paths miss.
            await self._ensure_graph_initialized(use_checkpointer=use_checkpointer)

            # 초기 상태 생성 (event_handler를 상태에 포함)
            initial_state = self._create_initial_state(user_input)
            initial_state["_event_handler"] = event_handler

            # Phase 2.1: 메모리 컨텍스트 로드
            await self._load_memory_context(initial_state, user_input)

            # Phase 4.7: 연구 템플릿 자동 선택 및 적용
            await self._apply_research_template(initial_state, query)

            # 독립 research_sessions 테이블에 세션 기록 (M-6 해결)
            await self._record_session_start(user_input)

            try:
                # 워크플로우 실행
                add_span_event(span, "starting_graph_execution")
                if use_checkpointer:
                    logger.debug("[ExecuteWorkflow] Executing with checkpointer (distributed state management)")
                    config = {
                        "configurable": {"thread_id": user_input["session_id"]},
                        "recursion_limit": 50  # 재시도를 위한 recursion limit 증가
                    }
                else:
                    logger.debug("[ExecuteWorkflow] Executing in stateless mode")
                    config = {
                        "recursion_limit": 50  # 재시도를 위한 recursion limit 증가
                    }

                # 노드별 진행 상황 추적을 위해 astream 사용
                workflow_nodes = [
                    WorkflowNode.QUERY_CLS.value, WorkflowNode.SKILL_TOOL_SELECTOR.value,
                    WorkflowNode.HYPOTHESIS_GENERATION.value,  # Phase 2.5
                    WorkflowNode.SEARCH_ORCHESTRATOR.value,
                    WorkflowNode.HYPOTHESIS_EVALUATION.value,  # Phase 2.5
                    WorkflowNode.REPLANNER.value,  # Phase 2.4
                    WorkflowNode.ANALYSIS_ORCHESTRATOR.value,
                    WorkflowNode.GENERATION_ORCHESTRATOR.value, WorkflowNode.RESULT_INTEGRATOR.value,
                    WorkflowNode.FACT_CHECK.value, WorkflowNode.QUALITY_VALIDATOR.value,
                    WorkflowNode.MISSION_PLANNER.value,
                    WorkflowNode.MISSION_APPROVAL.value,
                    WorkflowNode.MISSION_EXECUTOR.value,
                    WorkflowNode.MISSION_VALIDATOR.value,
                    WorkflowNode.MISSION_INTEGRATOR.value,
                    WorkflowNode.RESP_GENERATOR.value,
                    WorkflowNode.RESEARCH_HARNESS.value,
                    WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
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

                            # Tracing: 노드 실행 이벤트
                            add_span_event(span, f"node_{node_name}_start", {
                                "step": current_step,
                                "total_steps": total_steps
                            })

                            # 이전 노드의 실행 시간 기록 (동적 ETA용)
                            from .events import (
                                get_node_label, estimate_remaining_time,
                                record_node_start, record_node_end,
                            )
                            wf_id = user_input.get("session_id", "")
                            if current_step > 1:
                                # 이전 노드 완료 기록
                                prev_idx = workflow_nodes.index(node_name) - 1
                                if prev_idx >= 0:
                                    record_node_end(workflow_nodes[prev_idx], wf_id)

                            # 현재 노드 시작 기록
                            record_node_start(node_name, wf_id)

                            # 노드 시작 이벤트 (structured progress)
                            await event_handler.on_node_start(
                                node_name,
                                current_step,
                                total_steps,
                                step_name=get_node_label(node_name),
                                estimated_remaining_s=estimate_remaining_time(node_name),
                            )

                            # 노드 완료 이벤트 (state에서 필요한 정보 추출)
                            node_result = {
                                "node": node_name,
                                "step": current_step
                            }
                            await event_handler.on_node_complete(node_name, node_result)

                            # Tracing: 노드 완료 이벤트
                            add_span_event(span, f"node_{node_name}_complete")

                        # 마지막 상태 저장
                        final_state = state

                # 마지막 노드의 실행 시간 기록
                if workflow_nodes:
                    from .events import record_node_end
                    record_node_end(workflow_nodes[-1], user_input.get("session_id", ""))

                # 결과 생성
                add_span_event(span, "generating_result")
                result = self._create_workflow_result(final_state)

                # 성공적인 결과 캐싱
                if (
                    result["success"]
                    and result["response"]
                    and _mission_validation_passed(result)
                    and should_cache_harness_result(
                        result,
                        cache_policy=settings.RESEARCH_HARNESS_CACHE_POLICY,
                    )
                ):
                    # 스마트 캐시에 저장 (활성화된 경우)
                    if settings.SMART_CACHE_ENABLED:
                        add_span_event(span, "saving_to_smart_cache")
                        await self._save_to_smart_cache(
                            query=query,
                            result=result,
                            final_state=final_state,
                            user_id=user_id,
                            session_id=user_input.get("session_id")
                        )

                    # 기존 Redis 캐시에도 저장 (폴백용)
                    add_span_event(span, "saving_to_redis_cache")
                    await self._cache_workflow_result(cache_key, result)
                elif result["success"] and result["response"]:
                    add_span_event(span, "cache_skipped_validation_policy")

                # 데이터셋 자동 저장 (LLM 호출이 있었을 경우)
                await self._auto_save_dataset()

                # 워크플로우 완료 이벤트
                await event_handler.on_workflow_complete(result)

                # Tracing: 성공 완료
                add_span_event(span, "workflow_completed", {"success": result["success"]})
                set_span_attributes(span, {
                    "workflow.success": result["success"],
                    "workflow.nodes_executed": current_step
                })

                # Phase 2.1: 에피소드 메모리 저장
                await self._save_episode_memory(user_input, result, final_state)

                if result.get("success"):
                    # 세션 상태를 completed로 업데이트
                    await self._record_session_complete(
                        user_input, result, final_state
                    )
                elif _is_gate_harness_blocked(final_state):
                    await self._record_session_harness_blocked(
                        user_input, result, final_state
                    )

                logger.debug("[ExecuteWorkflow] Completed successfully")
                return result

            except Exception as e:
                # GraphInterrupt: interrupt_before=EXECUTION_APPROVAL 발동
                # Generic Exception catch 이전에 처리해야 SSE approval_request 이벤트가 발행됨
                try:
                    from langgraph.errors import GraphInterrupt
                    if isinstance(e, GraphInterrupt):
                        add_span_event(span, "workflow_interrupted_for_approval")
                        current_graph_state = await self.graph.aget_state(config)
                        pending = current_graph_state.values.get("pending_approvals", [])
                        session_id = user_input.get("session_id", "")
                        await event_handler.on_approval_request(pending, session_id)
                        logger.info(
                            f"[ExecuteWorkflow] GraphInterrupt: approval_request sent "
                            f"for session={session_id}, pending={len(pending)}"
                        )
                        return {
                            "success": True,
                            "interrupted": True,
                            "response": None,
                            "pending_approvals": pending,
                            "execution_time_ms": int(
                                (datetime.now() - initial_state["execution_start"]).total_seconds() * 1000
                            ),
                            "errors": [],
                        }
                except ImportError:
                    pass  # langgraph.errors 미설치 시 일반 에러로 처리

                import traceback
                traceback.print_exc()
                logger.error(f"[ExecuteWorkflow] Workflow execution failed: {str(e)}")

                # Tracing: 에러 기록
                add_span_event(span, "workflow_error", {"error": str(e)})
                set_span_attributes(span, {"workflow.error": True, "error.message": str(e)})

                # 에러 이벤트
                await event_handler.on_workflow_error(e)

                # 세션 상태를 failed로 업데이트
                await self._record_session_failed(user_input, e)

                return self._create_error_result(e, initial_state)

    async def _check_smart_cache(
        self,
        query: str,
        user_id: str = None,
        autonomy_level: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        스마트 캐시에서 유사 쿼리 검색

        pgvector를 사용하여 의미론적으로 유사한 캐시된 응답을 찾습니다.
        """
        try:
            print("[DEBUG] Checking smart cache (pgvector semantic search)...")

            cache_result = await smart_cache_manager.get_cached_response(
                query=query,
                user_id=user_id,
                metadata_filter={
                    "autonomy_level": _resolve_autonomy_level(autonomy_level)
                },
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
                result["timestamp"] = datetime.now().isoformat()

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
            quality_score = _coerce_quality_score(result.get("quality_score"), 0.7)

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
                    "detected_language": final_state.get("detected_language"),
                    "autonomy_level": _resolve_autonomy_level(
                        final_state.get("autonomy_level")
                    ),
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


    def _generate_cache_key(
        self,
        query: str,
        user_id: Optional[str] = None,
        autonomy_level: Optional[int] = None,
    ) -> str:
        """
        캐시 키 생성

        Args:
            query: 쿼리 텍스트
            user_id: 사용자 ID (선택적, USER_SPECIFIC_CACHE가 활성화된 경우 사용)

        Returns:
            생성된 캐시 키
        """
        query_normalized = query.strip().lower()
        cache_scope = f"<AUTONOMY>{_resolve_autonomy_level(autonomy_level)}</AUTONOMY>"

        # 사용자별 캐시 분리 옵션 (개인화된 응답이 필요한 경우)
        if user_id and settings.USER_SPECIFIC_CACHE:
            cache_input = f"<USER_ID>{user_id}</USER_ID>{cache_scope}{query_normalized}"
        else:
            cache_input = f"{cache_scope}{query_normalized}"

        query_hash = hashlib.md5(cache_input.encode('utf-8')).hexdigest()
        return cache_manager.make_key("workflow_response", query_hash)


    async def _check_cached_response(self, cache_key: str) -> Dict[str, Any]:
        """캐시된 응답 확인"""
        print(f"[DEBUG] Checking workflow response cache with key: {cache_key}")
        cached_response = await cache_manager.get(cache_key, deserialize="json")

        if cached_response:
            print("[DEBUG] Found cached workflow response, returning cached result")
            cached_response["cache_hit"] = True
            cached_response["timestamp"] = datetime.now().isoformat()
            return cached_response

        print("[DEBUG] No cached response found, executing workflow")
        return None

    def _create_initial_state(self, user_input: Dict[str, Any]) -> AgentState:
        """초기 상태 생성"""
        return AgentState(
            user_id=user_input["user_id"],
            session_id=user_input["session_id"],
            conversation_id=user_input.get("conversation_id"),
            original_query=user_input["query"],
            query_intent=None,
            query_embedding=None,
            detected_language=None,
            query_classification=None,
            thinking_strategy=None,
            thinking_trace=[],
            task_dag=None,
            required_agents=[],
            search_results=[],
            analysis_results=[],
            generation_results=[],
            memory_context=None,  # Phase 2.1: 3계층 메모리 컨텍스트
            search_synthesis=None,  # Phase 2: LLM 검색 결과 종합
            search_metadata=None,  # Phase 2: 검색 메타데이터
            integrated_results=None,
            quality_score=None,
            quality_feedback=None,
            harness_mode=None,
            harness_contract={},
            harness_runs=[],
            harness_verdict=None,
            harness_score=None,
            harness_failed_checks=[],
            harness_repair_plan=None,
            harness_repair_attempts=0,
            harness_metadata={},
            final_response=None,
            response_metadata=None,
            execution_start=datetime.now(),
            execution_steps=[],
            errors=[],
            retry_count=0,
            execution_time_ms=None,
            tokens_used=None,
            api_calls_made=None,
            # Phase 4.7: Research Templates
            template_id=None,
            template_config=None,
            # Phase 8: A2UI (Agent-to-User Interface)
            needs_ui=user_input.get("needs_ui"),
            ui_frame=None,
            ui_submission=user_input.get("ui_submission"),
            # Phase 3: 채널 소스 (query_history.channel_source 초기 기록용)
            channel_source=user_input.get("channel_source", "api"),
            channel_type=user_input.get("channel_type"),
            channel_id=user_input.get("channel_id"),
            # Agent Autonomy Control
            autonomy_level=(
                _resolve_autonomy_level(user_input.get("autonomy_level"))
            ),
            # Mission Runtime
            use_mission_runtime=bool(
                (user_input.get("preferences") or {}).get("use_mission_runtime", False)
            ),
            mission_id=None,
            mission=None,
            mission_plan=None,
            validation_contract=None,
            mission_status=None,
            mission_events=[],
            mission_task_results=[],
            validator_runs=[],
            validation_summary=None,
        )

    def _create_workflow_result(self, final_state: AgentState) -> Dict[str, Any]:
        """워크플로우 결과 생성"""
        if _is_gate_harness_blocked(final_state):
            errors = list(final_state.get("errors") or [])
            if "research_harness_gate_failed" not in errors:
                errors.append("research_harness_gate_failed")
            return {
                "success": False,
                "response": _harness_blocked_message(final_state),
                "blocked_response": final_state.get("final_response"),
                "metadata": final_state.get("response_metadata") or {},
                "execution_time_ms": final_state["execution_time_ms"],
                "quality_score": _coerce_quality_score(final_state.get("quality_score")),
                "errors": errors,
                "cache_hit": False,
                "execution_steps": len(final_state["execution_steps"]),
                "retry_count": final_state.get("retry_count", 0),
                "channel_source": final_state.get("channel_source", "api"),
            }

        result = {
            "success": True,
            "response": final_state["final_response"],
            "metadata": final_state["response_metadata"],
            "execution_time_ms": final_state["execution_time_ms"],
            "quality_score": _coerce_quality_score(final_state.get("quality_score")),
            "errors": final_state["errors"],
            "cache_hit": False,
            "execution_steps": len(final_state["execution_steps"]),
            "retry_count": final_state.get("retry_count", 0),
            # Phase 3: 채널 소스 — query_history 저장 시 활용
            "channel_source": final_state.get("channel_source", "api"),
        }

        # Phase 4.7: 템플릿 정보 포함
        if final_state.get("template_id"):
            result["template_id"] = final_state["template_id"]

        # Phase 2.7: 비용 정보 포함
        if final_state.get("cumulative_cost") is not None:
            result["cost_info"] = {
                "cumulative_cost": final_state["cumulative_cost"],
                "budget": final_state.get("cost_budget"),
                "cost_breakdown": final_state.get("cost_tracking", {}),
            }

        return result

    def _create_error_result(self, error: Exception, initial_state: AgentState) -> Dict[str, Any]:
        """오류 결과 생성"""
        return {
            "success": False,
            "error": str(error),
            "partial_state": initial_state,
            "cache_hit": False,
            "execution_time_ms": int((datetime.now() - initial_state["execution_start"]).total_seconds() * 1000)
        }

    async def _load_memory_context(
        self, state: AgentState, user_input: Dict[str, Any]
    ) -> None:
        """Phase 2.1: 3계층 메모리에서 컨텍스트 로드"""
        try:
            from neos.memory.manager import memory_manager
            context = await memory_manager.build_context(
                user_id=user_input.get("user_id", ""),
                query=user_input.get("query", ""),
                session_id=user_input.get("session_id"),
            )
            state["memory_context"] = context
        except Exception as e:
            logger.debug(f"[Workflow] Memory context load skipped: {e}")

    async def _apply_research_template(
        self, state: AgentState, query: str
    ) -> None:
        """Phase 4.7: 연구 템플릿 자동 선택 및 적용

        쿼리에 맞는 템플릿을 LLM으로 선택하고,
        research_guidance를 쿼리 앞에 prepend하여 연구 방향을 설정한다.
        """
        try:
            from neos.templates.template_selector import TemplateSelector

            selector = TemplateSelector()
            result = await selector.select(query)

            if result is None:
                return

            template = result["template"]
            params = result["params"]

            # 상태에 템플릿 정보 저장
            state["template_id"] = template.template_id
            state["template_config"] = {
                "workflow_overrides": template.workflow_overrides,
                "required_agents": template.required_agents,
                "recommended_skills": template.recommended_skills,
                "output_format": template.output_format,
                "params": params,
            }

            # research_guidance를 원본 쿼리에 prepend
            if template.research_guidance:
                state["original_query"] = (
                    f"[연구 지침]\n{template.research_guidance}\n\n"
                    f"[사용자 질문]\n{query}"
                )

            logger.info(
                f"[Workflow] Research template applied: {template.name} "
                f"(id={template.template_id})"
            )
        except Exception as e:
            logger.debug(f"[Workflow] Template selection skipped: {e}")

    async def _save_episode_memory(
        self, user_input: Dict[str, Any], result: Dict[str, Any],
        final_state: AgentState
    ) -> None:
        """Phase 2.1: 워크플로우 완료 시 에피소드 메모리 저장"""
        if not result.get("success"):
            return
        try:
            from neos.memory.manager import memory_manager
            sources = []
            for sr in (final_state.get("search_results") or []):
                sources.append({"source": sr.source, "title": sr.title, "url": sr.url})

            key_findings = result.get("response", "")[:500]  # 핵심 발견 요약 (앞 500자)

            await memory_manager.save_episode(
                user_id=user_input.get("user_id", ""),
                session_id=user_input.get("session_id", ""),
                query=user_input.get("query", ""),
                key_findings=key_findings,
                sources_used=sources[:10],  # 상위 10개 소스만
                quality_score=result.get("quality_score", 0.0),
                metadata={
                    "execution_time_ms": result.get("execution_time_ms"),
                    "intent": final_state.get("query_intent"),
                },
            )
        except Exception as e:
            logger.debug(f"[Workflow] Episode memory save skipped: {e}")

    async def _record_session_start(self, user_input: Dict[str, Any]) -> None:
        """워크플로우 시작 시 research_sessions 테이블에 세션 기록"""
        try:
            from neos.api.services.research_session_service import research_session_service
        except ImportError as e:
            logger.error(f"[Workflow] Cannot import research_session_service: {e}")
            return

        try:
            await research_session_service.create_session(
                thread_id=user_input.get("session_id", ""),
                user_id=user_input.get("user_id", ""),
                original_query=user_input.get("query", ""),
            )
        except Exception as e:
            # 세션 기록 실패는 워크플로우 실행을 차단하지 않음
            logger.warning(f"[Workflow] Failed to record session start: {e}")

    async def _record_session_complete(
        self, user_input: Dict[str, Any], result: Dict[str, Any],
        final_state: AgentState
    ) -> None:
        """워크플로우 완료 시 세션 상태 업데이트"""
        try:
            from neos.api.services.research_session_service import research_session_service
        except ImportError as e:
            logger.error(f"[Workflow] Cannot import research_session_service: {e}")
            return

        try:
            metadata_updates = {
                "quality_score": result.get("quality_score"),
                "search_results_count": len(final_state.get("search_results", [])),
                "execution_time_ms": result.get("execution_time_ms"),
                "errors": final_state.get("errors", []),
            }
            harness_metadata = (result.get("metadata") or {}).get("harness")
            if harness_metadata:
                metadata_updates["harness"] = harness_metadata
            await research_session_service.update_session_status(
                thread_id=user_input.get("session_id", ""),
                status="completed",
                metadata_updates=metadata_updates,
            )
        except Exception as e:
            logger.warning(f"[Workflow] Failed to record session completion: {e}")

    async def _record_session_harness_blocked(
        self, user_input: Dict[str, Any], result: Dict[str, Any],
        final_state: AgentState
    ) -> None:
        """워크플로우가 gate harness에서 차단되었을 때 세션 상태 업데이트"""
        try:
            from neos.api.services.research_session_service import research_session_service
        except ImportError as e:
            logger.error(f"[Workflow] Cannot import research_session_service: {e}")
            return

        try:
            await research_session_service.update_session_status(
                thread_id=user_input.get("session_id", ""),
                status="failed",
                metadata_updates={
                    "reason": "research_harness_gate_failed",
                    "quality_score": result.get("quality_score"),
                    "search_results_count": len(final_state.get("search_results", [])),
                    "execution_time_ms": result.get("execution_time_ms"),
                    "errors": result.get("errors", []),
                    "harness": (result.get("metadata") or {}).get("harness", {}),
                },
            )
        except Exception as e:
            logger.warning(f"[Workflow] Failed to record harness-blocked session: {e}")

    async def _record_session_failed(
        self, user_input: Dict[str, Any], error: Exception
    ) -> None:
        """워크플로우 실패 시 세션 상태 업데이트"""
        try:
            from neos.api.services.research_session_service import research_session_service
        except ImportError as e:
            logger.error(f"[Workflow] Cannot import research_session_service: {e}")
            return

        try:
            await research_session_service.update_session_status(
                thread_id=user_input.get("session_id", ""),
                status="failed",
                metadata_updates={"error": str(error)},
            )
        except Exception as e:
            logger.warning(f"[Workflow] Failed to record session failure: {e}")

    async def _cache_workflow_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """워크플로우 결과 캐싱"""
        if not should_cache_harness_result(
            result,
            cache_policy=settings.RESEARCH_HARNESS_CACHE_POLICY,
        ):
            print("[DEBUG] Workflow response cache skipped by harness policy")
            return

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
                WorkflowNode.QUERY_CLS.value: bool(self.query_classifier),
                WorkflowNode.SEARCH_ORCHESTRATOR.value: bool(self.search_orchestrator),
                WorkflowNode.ANALYSIS_ORCHESTRATOR.value: bool(self.analysis_orchestrator),
                WorkflowNode.GENERATION_ORCHESTRATOR.value: bool(self.generation_orchestrator),
                WorkflowNode.RESULT_INTEGRATOR.value: bool(self.result_processor),
                "result_processor": bool(self.result_processor),
                WorkflowNode.FACT_CHECK.value: bool(self.fact_check_processor),
                WorkflowNode.QUALITY_VALIDATOR.value: bool(self.quality_validator),
                WorkflowNode.RESP_GENERATOR.value: bool(self.response_generator),
                WorkflowNode.RESEARCH_HARNESS.value: bool(self.research_harness_processor),
                WorkflowNode.RESEARCH_HARNESS_REPAIR.value: bool(
                    self.research_harness_repair_processor
                ),
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
            "timestamp": datetime.now().isoformat(),
            "state_management": "distributed"
        }

        # 컴포넌트 상태 확인
        try:
            health_status["components"][WorkflowNode.QUERY_CLS.value] = "healthy"
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


    async def cleanup(self):
        """
        워크플로우 리소스 정리

        LLM 객체들의 aiohttp 세션을 명시적으로 정리하여
        "Unclosed client session" 경고를 방지합니다.

        CLI 또는 테스트 환경에서 워크플로우 실행 후 호출해야 합니다.
        """
        logger.info("[MultiAgentWorkflow] Cleaning up resources...")

        try:
            # ConversationContextProcessor LLM 정리
            if hasattr(self.conversation_context_processor, '_llm') and self.conversation_context_processor._llm:
                try:
                    # Langchain LLM의 aiohttp 세션 정리 시도
                    if hasattr(self.conversation_context_processor._llm, 'async_client'):
                        await self.conversation_context_processor._llm.async_client.aclose()
                    logger.debug("[Cleanup] ConversationContextProcessor LLM cleaned")
                except Exception as e:
                    logger.debug(f"[Cleanup] ConversationContextProcessor LLM cleanup: {e}")

            # SearchOrchestrator LLM 정리
            if hasattr(self.search_orchestrator, '_llm') and self.search_orchestrator._llm:
                try:
                    if hasattr(self.search_orchestrator._llm, 'async_client'):
                        await self.search_orchestrator._llm.async_client.aclose()
                    logger.debug("[Cleanup] SearchOrchestrator LLM cleaned")
                except Exception as e:
                    logger.debug(f"[Cleanup] SearchOrchestrator LLM cleanup: {e}")

            # ResponseGenerator LLM 정리
            if hasattr(self.response_generator, '_llm') and self.response_generator._llm:
                try:
                    if hasattr(self.response_generator._llm, 'async_client'):
                        await self.response_generator._llm.async_client.aclose()
                    logger.debug("[Cleanup] ResponseGenerator LLM cleaned")
                except Exception as e:
                    logger.debug(f"[Cleanup] ResponseGenerator LLM cleanup: {e}")

            logger.info("[MultiAgentWorkflow] ✅ Cleanup completed")

        except Exception as e:
            logger.warning(f"[MultiAgentWorkflow] Cleanup error (non-critical): {e}")


async def _register_pending_approvals_db(
    pending: list,
    user_id: str,
    session_id: str,
) -> None:
    """pending_approvals 추적 테이블에 승인 요청을 등록한다."""
    from datetime import timedelta
    from neos.database.connection import db_manager
    from neos.utils.time_utils import utc_now_naive

    now = utc_now_naive()
    for item in pending:
        expires_at = now + timedelta(seconds=settings.APPROVAL_TIMEOUT_SECONDS)
        try:
            await db_manager.execute(
                """
                INSERT INTO pending_approvals
                    (session_id, request_id, user_id, skill_name, requested_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (request_id) DO NOTHING
                """,
                session_id,
                item.get("request_id", ""),
                user_id,
                item.get("skill_name", ""),
                now,
                expires_at,
            )
        except Exception as exc:
            logger.debug("pending_approvals 등록 실패 (non-critical): %s", exc)


# 전역 워크플로우 인스턴스 (리팩토링된 버전)
multi_agent_workflow = MultiAgentWorkflow()
