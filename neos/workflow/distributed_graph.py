"""
분산 멀티에이전트 워크플로우 그래프

기존 중앙 집중식 워크플로우를 분산 시스템으로 재구성.
이벤트 기반 아키텍처로 에이전트들이 자율적으로 협력.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END

from neos.workflow.state import AgentState, WorkflowConfig
from neos.workflow.distributed import (
    MessageBus,
    Event,
    EventType,
    DistributedAgentRegistry,
    AgentCapability,
    HierarchicalStateManager,
    DistributedWorkQueue,
    Task,
    TaskPriority,
    AgentSupervisor,
    CollaborationProtocol,
    get_message_bus,
    get_agent_registry,
    get_state_manager,
    get_work_queue,
    get_supervisor,
    get_collaboration_protocol
)
from neos.workflow.processors import ResultProcessor, QualityValidator, ResponseGenerator
from neos.workflow.utils import QueryClassifier
from neos.workflow.checkpointer import get_checkpointer
from neos.utils.cache import cache_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class DistributedMultiAgentWorkflow:
    """
    분산 멀티에이전트 워크플로우

    Features:
    - 이벤트 기반 에이전트 통신
    - 자율적 작업 발견 및 실행
    - 동적 에이전트 등록/발견
    - 작업 큐 기반 부하 분산
    - Supervisor 기반 자가 치유
    - 협력 프로토콜 지원
    """

    def __init__(self):
        self.config = WorkflowConfig()

        # 분산 시스템 컴포넌트
        self.message_bus: Optional[MessageBus] = None
        self.registry: Optional[DistributedAgentRegistry] = None
        self.state_manager: Optional[HierarchicalStateManager] = None
        self.work_queue: Optional[DistributedWorkQueue] = None
        self.supervisor: Optional[AgentSupervisor] = None
        self.collaboration: Optional[CollaborationProtocol] = None

        # 기존 컴포넌트 (하위 호환성)
        self.query_classifier: Optional[QueryClassifier] = None
        self.result_processor: Optional[ResultProcessor] = None
        self.quality_validator: Optional[QualityValidator] = None
        self.response_generator: Optional[ResponseGenerator] = None

        # 자율 에이전트들 (동적으로 등록됨)
        self.autonomous_agents: Dict[str, Any] = {}

        # 워크플로우 그래프
        self.graph = None
        self._graph_initialized = False

        self.initialized = False

    async def initialize(self):
        """워크플로우 초기화"""
        if self.initialized:
            return

        logger.info("[DistributedWorkflow] Initializing distributed workflow...")

        # 분산 시스템 컴포넌트 초기화
        self.message_bus = await get_message_bus()
        self.registry = await get_agent_registry()
        self.state_manager = await get_state_manager()
        self.work_queue = await get_work_queue()
        self.supervisor = await get_supervisor()
        self.collaboration = await get_collaboration_protocol()

        # 기존 컴포넌트 초기화
        self.query_classifier = QueryClassifier(self.config)
        self.result_processor = ResultProcessor()
        self.quality_validator = QualityValidator(self.config)
        self.response_generator = ResponseGenerator()

        # 이벤트 리스너 설정
        await self._setup_event_listeners()

        # 워커 풀 시작
        await self.work_queue.start()

        # Supervisor 시작
        await self.supervisor.start()

        self.initialized = True
        logger.info("[DistributedWorkflow] Distributed workflow initialized")

    async def _setup_event_listeners(self):
        """이벤트 리스너 설정"""
        # 워크플로우 관련 이벤트 구독
        await self.message_bus.subscribe(
            EventType.WORKFLOW_STARTED,
            self._handle_workflow_started
        )
        await self.message_bus.subscribe(
            EventType.WORKFLOW_COMPLETED,
            self._handle_workflow_completed
        )

        logger.debug("[DistributedWorkflow] Event listeners set up")

    async def register_autonomous_agent(self, agent: Any):
        """
        자율 에이전트 등록

        Args:
            agent: AutonomousAgent 인스턴스
        """
        logger.info(f"[DistributedWorkflow] Registering autonomous agent: {agent.name}")

        # 에이전트 초기화
        await agent.initialize()

        # 에이전트 시작
        await agent.start()

        # Supervisor에 등록
        await self.supervisor.supervise_agent(
            agent,
            agent.agent_id,
            restart_callback=lambda: agent.start()
        )

        self.autonomous_agents[agent.agent_id] = agent

        logger.info(
            f"[DistributedWorkflow] Agent {agent.name} registered and started "
            f"with ID: {agent.agent_id}"
        )

    async def execute_workflow(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        워크플로우 실행 (분산 방식)

        Args:
            user_input: 사용자 입력

        Returns:
            실행 결과
        """
        if not self.initialized:
            await self.initialize()

        query = user_input["query"]
        logger.info(f"[DistributedWorkflow] Starting distributed workflow for query: {query[:50]}...")

        # 초기 상태 생성
        initial_state = self._create_initial_state(user_input)

        # 상태 관리자에 전역 상태 설정
        await self.state_manager.set_global_state(initial_state)

        try:
            # 1. 쿼리 분류
            logger.info("[DistributedWorkflow] Step 1: Query classification")
            classification_result = await self.query_classifier.classify_query(initial_state)
            await self.state_manager.update_global_state(classification_result)

            # 2. 필요한 작업들을 작업 큐에 제출 (이벤트 기반)
            logger.info("[DistributedWorkflow] Step 2: Task submission")
            required_agents = classification_result.get("required_agents", [])

            task_ids = []
            for agent_name in required_agents:
                # 에이전트 타입별 능력 매핑
                capability = self._map_agent_to_capability(agent_name)

                if capability:
                    task_id = await self.work_queue.submit_simple_task(
                        description=f"Execute {agent_name} for query: {query[:50]}",
                        capability=capability,
                        payload={
                            "query": query,
                            "context": {
                                "user_id": user_input["user_id"],
                                "session_id": user_input["session_id"],
                                "query_intent": classification_result.get("query_intent"),
                                "detected_language": classification_result.get("detected_language")
                            }
                        },
                        priority=TaskPriority.NORMAL,
                        requester="distributed_workflow"
                    )
                    task_ids.append(task_id)

            logger.info(f"[DistributedWorkflow] Submitted {len(task_ids)} tasks to queue")

            # 3. 작업 완료 대기 (이벤트 기반)
            logger.info("[DistributedWorkflow] Step 3: Waiting for task completion")
            completed_tasks = await self._wait_for_tasks(task_ids, timeout=120.0)

            logger.info(
                f"[DistributedWorkflow] {len(completed_tasks)} tasks completed "
                f"out of {len(task_ids)}"
            )

            # 4. 결과 통합
            logger.info("[DistributedWorkflow] Step 4: Result integration")
            global_state = await self.state_manager.get_global_state()
            integrated_state = await self.result_processor.integrate_results(global_state)
            await self.state_manager.update_global_state(integrated_state)

            # 5. 품질 검증
            logger.info("[DistributedWorkflow] Step 5: Quality validation")
            validated_state = await self.quality_validator.validate_quality(integrated_state)
            await self.state_manager.update_global_state(validated_state)

            # 6. 응답 생성
            logger.info("[DistributedWorkflow] Step 6: Response generation")
            final_state = await self.response_generator.generate_response(validated_state)

            # 결과 반환
            result = self._create_workflow_result(final_state)

            logger.info("[DistributedWorkflow] Workflow completed successfully")

            return result

        except Exception as e:
            logger.error(f"[DistributedWorkflow] Workflow failed: {e}", exc_info=True)
            return self._create_error_result(e, initial_state)

    def _map_agent_to_capability(self, agent_name: str) -> Optional[AgentCapability]:
        """에이전트 이름을 능력으로 매핑"""
        mapping = {
            "knowledge_search": AgentCapability.KNOWLEDGE_SEARCH,
            "realtime_info_search": AgentCapability.REALTIME_SEARCH,
            "realtime_data_search": AgentCapability.DATA_SEARCH,
            "multi_query_search": AgentCapability.WEB_SEARCH,
            "deep_research": AgentCapability.DEEP_RESEARCH,
            "web_lookup": AgentCapability.WEB_SEARCH,
            "data_analysis": AgentCapability.DATA_ANALYSIS,
            "comparative_analysis": AgentCapability.COMPARATIVE_ANALYSIS,
            "web_content_analysis": AgentCapability.WEB_CONTENT_ANALYSIS,
            "image_generation": AgentCapability.IMAGE_GENERATION,
            "api_call": AgentCapability.API_CALL,
            "file_processing": AgentCapability.FILE_PROCESSING,
            "task_creation": AgentCapability.TASK_PLANNING
        }

        return mapping.get(agent_name)

    async def _wait_for_tasks(
        self,
        task_ids: List[str],
        timeout: float = 120.0
    ) -> List[Task]:
        """
        작업 완료 대기

        Args:
            task_ids: 작업 ID 리스트
            timeout: 타임아웃 (초)

        Returns:
            완료된 작업 리스트
        """
        # Early return for empty task list
        if not task_ids:
            return []

        start_time = datetime.now()
        completed = []

        while len(completed) < len(task_ids):
            # 타임아웃 체크
            if (datetime.now() - start_time).total_seconds() > timeout:
                logger.warning(
                    f"[DistributedWorkflow] Task waiting timed out "
                    f"({len(completed)}/{len(task_ids)} completed)"
                )
                break

            # 작업 상태 확인
            for task_id in task_ids:
                if task_id in [t.task_id for t in completed]:
                    continue

                task = self.work_queue.get_task(task_id)

                if task and task.status.value in ["completed", "failed"]:
                    completed.append(task)

            # 잠시 대기
            await asyncio.sleep(0.5)

        return completed

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
            execution_start=datetime.now(),
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
            "response": final_state.get("final_response"),
            "metadata": final_state.get("response_metadata"),
            "execution_time_ms": final_state.get("execution_time_ms"),
            "quality_score": final_state.get("quality_score", 0.0),
            "errors": final_state.get("errors", []),
            "cache_hit": False,
            "execution_steps": len(final_state.get("execution_steps", [])),
            "retry_count": final_state.get("retry_count", 0),
            "distributed": True
        }

    def _create_error_result(self, error: Exception, initial_state: AgentState) -> Dict[str, Any]:
        """오류 결과 생성"""
        return {
            "success": False,
            "error": str(error),
            "partial_state": initial_state,
            "cache_hit": False,
            "execution_time_ms": int(
                (datetime.now() - initial_state["execution_start"]).total_seconds() * 1000
            ),
            "distributed": True
        }

    async def _handle_workflow_started(self, event: Event):
        """워크플로우 시작 이벤트 핸들러"""
        logger.info(f"[DistributedWorkflow] Workflow started: {event.data.get('saga_id')}")

    async def _handle_workflow_completed(self, event: Event):
        """워크플로우 완료 이벤트 핸들러"""
        logger.info(f"[DistributedWorkflow] Workflow completed: {event.data.get('saga_id')}")

    async def get_statistics(self) -> Dict[str, Any]:
        """워크플로우 통계"""
        return {
            "autonomous_agents": len(self.autonomous_agents),
            "registry_stats": self.registry.get_statistics() if self.registry else {},
            "work_queue_stats": self.work_queue.get_statistics() if self.work_queue else {},
            "supervisor_stats": self.supervisor.get_statistics() if self.supervisor else {},
            "distributed_mode": True
        }

    async def health_check(self) -> Dict[str, Any]:
        """워크플로우 상태 확인"""
        return {
            "workflow": "healthy",
            "components": {
                "message_bus": "healthy" if self.message_bus and self.message_bus.initialized else "unhealthy",
                "registry": "healthy" if self.registry and self.registry.initialized else "unhealthy",
                "state_manager": "healthy" if self.state_manager and self.state_manager.initialized else "unhealthy",
                "work_queue": "healthy" if self.work_queue and self.work_queue.is_running else "unhealthy",
                "supervisor": "healthy" if self.supervisor and self.supervisor.is_running else "unhealthy",
            },
            "autonomous_agents": len(self.autonomous_agents),
            "timestamp": datetime.now().isoformat(),
            "mode": "distributed"
        }

    async def close(self):
        """워크플로우 종료"""
        logger.info("[DistributedWorkflow] Closing distributed workflow...")

        # 모든 자율 에이전트 중지
        for agent in self.autonomous_agents.values():
            try:
                await agent.stop()
            except Exception as e:
                logger.error(f"[DistributedWorkflow] Error stopping agent: {e}")

        # 컴포넌트 종료
        if self.work_queue:
            await self.work_queue.stop()

        if self.supervisor:
            await self.supervisor.stop()

        if self.state_manager:
            await self.state_manager.close()

        if self.registry:
            await self.registry.close()

        if self.message_bus:
            await self.message_bus.close()

        logger.info("[DistributedWorkflow] Distributed workflow closed")


# 전역 분산 워크플로우 인스턴스
distributed_workflow = DistributedMultiAgentWorkflow()
