"""
동적 에이전트 레지스트리

런타임에 에이전트를 등록/발견하고, 능력 기반으로 에이전트를 찾을 수 있는 레지스트리.
기존 agent_registry.py를 확장하여 분산 환경에 적합하도록 개선.
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .message_bus import MessageBus, Event, EventType, get_message_bus

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    """에이전트 상태"""
    INITIALIZING = "initializing"
    AVAILABLE = "available"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class AgentCapability(str, Enum):
    """에이전트 능력 정의"""
    # Search capabilities
    WEB_SEARCH = "web_search"
    KNOWLEDGE_SEARCH = "knowledge_search"
    REALTIME_SEARCH = "realtime_search"
    DEEP_RESEARCH = "deep_research"
    DATA_SEARCH = "data_search"

    # Analysis capabilities
    DATA_ANALYSIS = "data_analysis"
    COMPARATIVE_ANALYSIS = "comparative_analysis"
    WEB_CONTENT_ANALYSIS = "web_content_analysis"
    SENTIMENT_ANALYSIS = "sentiment_analysis"

    # Generation capabilities
    IMAGE_GENERATION = "image_generation"
    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"
    API_CALL = "api_call"
    FILE_PROCESSING = "file_processing"

    # Coordination capabilities
    TASK_PLANNING = "task_planning"
    TASK_COORDINATION = "task_coordination"
    RESULT_INTEGRATION = "result_integration"


@dataclass
class AgentMetadata:
    """에이전트 메타데이터"""
    agent_id: str
    name: str
    capabilities: List[AgentCapability]
    status: AgentStatus = AgentStatus.INITIALIZING
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    registration_time: datetime = field(default_factory=datetime.utcnow)

    # Performance metrics
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    average_response_time: float = 0.0

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """성공률 계산"""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks

    @property
    def is_healthy(self) -> bool:
        """헬스 체크 - 60초 내 heartbeat 있어야 함"""
        return (datetime.now() - self.last_heartbeat).total_seconds() < 60

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": [c.value for c in self.capabilities],
            "status": self.status.value,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "registration_time": self.registration_time.isoformat(),
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "average_response_time": self.average_response_time,
            "success_rate": self.success_rate,
            "metadata": self.metadata
        }


class DistributedAgentRegistry:
    """
    분산 에이전트 레지스트리

    Features:
    - 런타임 에이전트 등록/해제
    - 능력 기반 에이전트 발견
    - 자동 헬스체크 및 장애 에이전트 제거
    - 부하 분산을 위한 에이전트 선택
    - 이벤트 기반 상태 업데이트
    """

    def __init__(self, message_bus: Optional[MessageBus] = None):
        self.agents: Dict[str, AgentMetadata] = {}
        self.message_bus = message_bus

        # 능력별 인덱스 (빠른 검색)
        self.capability_index: Dict[AgentCapability, Set[str]] = {}

        # 헬스체크 태스크
        self.health_check_task: Optional[asyncio.Task] = None
        self.health_check_interval = 30  # 30초마다 헬스체크

        self.initialized = False

    async def initialize(self):
        """레지스트리 초기화"""
        if self.initialized:
            return

        logger.info("[AgentRegistry] Initializing agent registry...")

        # 메시지 버스 초기화
        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        # 이벤트 리스너 등록
        await self._setup_event_listeners()

        # 헬스체크 시작
        self.health_check_task = asyncio.create_task(self._health_check_loop())

        self.initialized = True
        logger.info("[AgentRegistry] Agent registry initialized")

    async def _setup_event_listeners(self):
        """이벤트 리스너 설정"""
        await self.message_bus.subscribe(
            EventType.AGENT_HEARTBEAT,
            self._handle_heartbeat
        )
        await self.message_bus.subscribe(
            EventType.AGENT_FAILED,
            self._handle_agent_failure
        )
        await self.message_bus.subscribe(
            EventType.TASK_COMPLETED,
            self._handle_task_completed
        )
        await self.message_bus.subscribe(
            EventType.TASK_FAILED,
            self._handle_task_failed
        )

    async def register_agent(self, metadata: AgentMetadata) -> bool:
        """
        에이전트 등록

        Args:
            metadata: 에이전트 메타데이터

        Returns:
            등록 성공 여부
        """
        try:
            agent_id = metadata.agent_id

            # 이미 등록된 에이전트면 업데이트
            if agent_id in self.agents:
                logger.info(f"[AgentRegistry] Updating existing agent: {metadata.name}")
                self.agents[agent_id] = metadata
            else:
                logger.info(f"[AgentRegistry] Registering new agent: {metadata.name} ({agent_id})")
                self.agents[agent_id] = metadata

            # 능력별 인덱스 업데이트
            for capability in metadata.capabilities:
                if capability not in self.capability_index:
                    self.capability_index[capability] = set()
                self.capability_index[capability].add(agent_id)

            # 등록 이벤트 발행
            await self.message_bus.publish(Event(
                event_id=f"reg-{agent_id}",
                event_type=EventType.AGENT_REGISTERED,
                source="agent_registry",
                data=metadata.to_dict()
            ))

            logger.info(
                f"[AgentRegistry] Agent registered: {metadata.name} "
                f"with capabilities: {[c.value for c in metadata.capabilities]}"
            )
            return True

        except Exception as e:
            logger.error(f"[AgentRegistry] Error registering agent: {e}")
            return False

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        에이전트 등록 해제

        Args:
            agent_id: 에이전트 ID

        Returns:
            해제 성공 여부
        """
        try:
            if agent_id not in self.agents:
                logger.warning(f"[AgentRegistry] Agent not found: {agent_id}")
                return False

            metadata = self.agents[agent_id]

            # 능력별 인덱스에서 제거
            for capability in metadata.capabilities:
                if capability in self.capability_index:
                    self.capability_index[capability].discard(agent_id)

            # 에이전트 제거
            del self.agents[agent_id]

            # 등록 해제 이벤트 발행
            await self.message_bus.publish(Event(
                event_id=f"unreg-{agent_id}",
                event_type=EventType.AGENT_UNREGISTERED,
                source="agent_registry",
                data={"agent_id": agent_id, "name": metadata.name}
            ))

            logger.info(f"[AgentRegistry] Agent unregistered: {metadata.name}")
            return True

        except Exception as e:
            logger.error(f"[AgentRegistry] Error unregistering agent: {e}")
            return False

    async def discover_by_capability(
        self,
        capability: AgentCapability,
        status: Optional[AgentStatus] = None,
        min_success_rate: float = 0.0
    ) -> List[AgentMetadata]:
        """
        능력 기반 에이전트 발견

        Args:
            capability: 필요한 능력
            status: 필터링할 상태 (선택적)
            min_success_rate: 최소 성공률 (0.0 ~ 1.0)

        Returns:
            조건에 맞는 에이전트 리스트
        """
        if capability not in self.capability_index:
            return []

        agent_ids = self.capability_index[capability]
        candidates = [self.agents[aid] for aid in agent_ids if aid in self.agents]

        # 상태 필터링
        if status:
            candidates = [a for a in candidates if a.status == status]

        # 성공률 필터링
        candidates = [a for a in candidates if a.success_rate >= min_success_rate]

        # 건강한 에이전트만
        candidates = [a for a in candidates if a.is_healthy]

        logger.debug(
            f"[AgentRegistry] Found {len(candidates)} agents with capability {capability.value}"
        )

        return candidates

    async def select_best_agent(
        self,
        capability: AgentCapability,
        strategy: str = "least_loaded"
    ) -> Optional[AgentMetadata]:
        """
        최적 에이전트 선택

        Args:
            capability: 필요한 능력
            strategy: 선택 전략 ("least_loaded", "best_performance", "round_robin")

        Returns:
            선택된 에이전트 또는 None
        """
        candidates = await self.discover_by_capability(
            capability,
            status=AgentStatus.AVAILABLE
        )

        if not candidates:
            logger.warning(f"[AgentRegistry] No available agents for capability {capability.value}")
            return None

        if strategy == "least_loaded":
            # 가장 적은 작업을 처리 중인 에이전트
            return min(candidates, key=lambda a: a.total_tasks - a.successful_tasks - a.failed_tasks)

        elif strategy == "best_performance":
            # 성공률과 응답 시간을 고려
            return max(candidates, key=lambda a: a.success_rate / (a.average_response_time + 1))

        elif strategy == "round_robin":
            # 단순 라운드 로빈
            return candidates[0]

        else:
            logger.warning(f"[AgentRegistry] Unknown strategy: {strategy}, using least_loaded")
            return min(candidates, key=lambda a: a.total_tasks)

    async def update_agent_status(self, agent_id: str, status: AgentStatus):
        """에이전트 상태 업데이트"""
        if agent_id in self.agents:
            self.agents[agent_id].status = status
            logger.debug(f"[AgentRegistry] Agent {agent_id} status updated to {status.value}")

    async def _handle_heartbeat(self, event: Event):
        """Heartbeat 이벤트 처리"""
        agent_id = event.data.get("agent_id")
        if agent_id and agent_id in self.agents:
            self.agents[agent_id].last_heartbeat = datetime.now()
            logger.debug(f"[AgentRegistry] Heartbeat received from {agent_id}")

    async def _handle_agent_failure(self, event: Event):
        """에이전트 실패 이벤트 처리"""
        agent_id = event.data.get("agent_id")
        if agent_id and agent_id in self.agents:
            self.agents[agent_id].status = AgentStatus.FAILED
            logger.warning(f"[AgentRegistry] Agent {agent_id} marked as failed")

    async def _handle_task_completed(self, event: Event):
        """작업 완료 이벤트 처리"""
        agent_id = event.data.get("agent_id")
        response_time = event.data.get("response_time", 0.0)

        if agent_id and agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.total_tasks += 1
            agent.successful_tasks += 1

            # 평균 응답 시간 업데이트
            if agent.average_response_time == 0:
                agent.average_response_time = response_time
            else:
                agent.average_response_time = (
                    agent.average_response_time * 0.9 + response_time * 0.1
                )

            logger.debug(f"[AgentRegistry] Task completed by {agent_id}")

    async def _handle_task_failed(self, event: Event):
        """작업 실패 이벤트 처리"""
        agent_id = event.data.get("agent_id")

        if agent_id and agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.total_tasks += 1
            agent.failed_tasks += 1
            logger.debug(f"[AgentRegistry] Task failed by {agent_id}")

    async def _health_check_loop(self):
        """헬스체크 루프"""
        logger.info("[AgentRegistry] Starting health check loop...")

        while True:
            try:
                await asyncio.sleep(self.health_check_interval)

                # 건강하지 않은 에이전트 찾기
                unhealthy_agents = [
                    agent_id
                    for agent_id, metadata in self.agents.items()
                    if not metadata.is_healthy
                ]

                # 건강하지 않은 에이전트 제거
                for agent_id in unhealthy_agents:
                    logger.warning(
                        f"[AgentRegistry] Agent {agent_id} is unhealthy, removing from registry"
                    )
                    await self.unregister_agent(agent_id)

                if unhealthy_agents:
                    logger.info(f"[AgentRegistry] Removed {len(unhealthy_agents)} unhealthy agents")

            except asyncio.CancelledError:
                logger.info("[AgentRegistry] Health check loop cancelled")
                break
            except Exception as e:
                logger.error(f"[AgentRegistry] Error in health check loop: {e}")

    def get_all_agents(self) -> List[AgentMetadata]:
        """모든 에이전트 조회"""
        return list(self.agents.values())

    def get_agent(self, agent_id: str) -> Optional[AgentMetadata]:
        """특정 에이전트 조회"""
        return self.agents.get(agent_id)

    def get_statistics(self) -> Dict[str, Any]:
        """레지스트리 통계"""
        return {
            "total_agents": len(self.agents),
            "agents_by_status": {
                status.value: len([a for a in self.agents.values() if a.status == status])
                for status in AgentStatus
            },
            "agents_by_capability": {
                cap.value: len(self.capability_index.get(cap, set()))
                for cap in AgentCapability
            },
            "average_success_rate": (
                sum(a.success_rate for a in self.agents.values()) / len(self.agents)
                if self.agents else 0.0
            )
        }

    async def close(self):
        """레지스트리 종료"""
        logger.info("[AgentRegistry] Closing agent registry...")

        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        self.initialized = False
        logger.info("[AgentRegistry] Agent registry closed")


# 전역 레지스트리 싱글톤
_agent_registry: Optional[DistributedAgentRegistry] = None


async def get_agent_registry() -> DistributedAgentRegistry:
    """전역 에이전트 레지스트리 인스턴스 가져오기"""
    global _agent_registry

    if _agent_registry is None:
        _agent_registry = DistributedAgentRegistry()
        await _agent_registry.initialize()

    return _agent_registry
