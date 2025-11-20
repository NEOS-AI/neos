"""
에이전트 협력 프로토콜

Contract Net Protocol과 협상 메커니즘을 구현하여
에이전트들이 동적으로 협력할 수 있도록 지원.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .message_bus import MessageBus, Event, EventType, get_message_bus
from .agent_registry import (
    DistributedAgentRegistry,
    AgentCapability,
    AgentStatus,
    get_agent_registry
)

logger = logging.getLogger(__name__)


class ProposalStatus(str, Enum):
    """제안 상태"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


@dataclass
class TaskAnnouncement:
    """작업 공고"""
    task_id: str
    description: str
    required_capability: AgentCapability
    requester: str
    deadline: Optional[datetime] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    reward: float = 1.0  # 작업 보상 (우선순위 등에 사용)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "required_capability": self.required_capability.value,
            "requester": self.requester,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "constraints": self.constraints,
            "reward": self.reward
        }


@dataclass
class Proposal:
    """에이전트 제안"""
    proposal_id: str
    task_id: str
    agent_id: str
    agent_name: str
    estimated_time: float  # 예상 소요 시간 (초)
    cost: float  # 비용 (추상적 단위)
    confidence: float  # 성공 확신도 (0.0 ~ 1.0)
    status: ProposalStatus = ProposalStatus.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)

    def score(self) -> float:
        """제안 점수 계산 (낮을수록 좋음)"""
        # 시간, 비용, 확신도를 종합적으로 고려
        return (self.estimated_time * 0.4 + self.cost * 0.3 +
                (1.0 - self.confidence) * 0.3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "estimated_time": self.estimated_time,
            "cost": self.cost,
            "confidence": self.confidence,
            "status": self.status.value,
            "score": self.score(),
            "metadata": self.metadata
        }


class ContractNetProtocol:
    """
    Contract Net Protocol 구현

    작업 공고 → 제안 수집 → 최적 에이전트 선택 → 작업 할당
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        registry: Optional[DistributedAgentRegistry] = None
    ):
        self.message_bus = message_bus
        self.registry = registry

        # 공고된 작업들
        self.announcements: Dict[str, TaskAnnouncement] = {}

        # 수신된 제안들
        self.proposals: Dict[str, List[Proposal]] = {}  # task_id -> proposals

        self.initialized = False

    async def initialize(self):
        """프로토콜 초기화"""
        if self.initialized:
            return

        logger.info("[ContractNet] Initializing Contract Net Protocol...")

        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        if self.registry is None:
            self.registry = await get_agent_registry()

        # 이벤트 구독
        await self._setup_subscriptions()

        self.initialized = True
        logger.info("[ContractNet] Contract Net Protocol initialized")

    async def _setup_subscriptions(self):
        """이벤트 구독 설정"""
        await self.message_bus.subscribe(
            EventType.NEGOTIATION_STARTED,
            self._handle_proposal_received
        )

    async def announce_task(
        self,
        announcement: TaskAnnouncement,
        wait_time: float = 5.0
    ) -> List[Proposal]:
        """
        작업 공고 및 제안 수집

        Args:
            announcement: 작업 공고
            wait_time: 제안 대기 시간 (초)

        Returns:
            수신된 제안 리스트
        """
        logger.info(
            f"[ContractNet] Announcing task {announcement.task_id} "
            f"requiring {announcement.required_capability.value}"
        )

        # 공고 등록
        self.announcements[announcement.task_id] = announcement
        self.proposals[announcement.task_id] = []

        # 공고 이벤트 발행
        await self.message_bus.publish(Event(
            event_id=f"announce-{announcement.task_id}",
            event_type=EventType.TASK_SUBMITTED,
            source=announcement.requester,
            data={
                **announcement.to_dict(),
                "announcement": True
            }
        ))

        # 제안 대기
        logger.info(f"[ContractNet] Waiting {wait_time}s for proposals...")
        await asyncio.sleep(wait_time)

        # 수신된 제안 반환
        proposals = self.proposals.get(announcement.task_id, [])
        logger.info(
            f"[ContractNet] Received {len(proposals)} proposals for task {announcement.task_id}"
        )

        return proposals

    async def submit_proposal(self, proposal: Proposal):
        """
        제안 제출

        Args:
            proposal: 에이전트의 제안
        """
        logger.info(
            f"[ContractNet] Agent {proposal.agent_id} submitting proposal "
            f"for task {proposal.task_id}"
        )

        # 제안 이벤트 발행
        await self.message_bus.publish(Event(
            event_id=f"proposal-{proposal.proposal_id}",
            event_type=EventType.NEGOTIATION_STARTED,
            source=proposal.agent_id,
            data=proposal.to_dict()
        ))

    async def _handle_proposal_received(self, event: Event):
        """제안 수신 처리"""
        proposal_data = event.data
        task_id = proposal_data.get("task_id")

        if task_id and task_id in self.announcements:
            proposal = Proposal(
                proposal_id=proposal_data["proposal_id"],
                task_id=task_id,
                agent_id=proposal_data["agent_id"],
                agent_name=proposal_data["agent_name"],
                estimated_time=proposal_data["estimated_time"],
                cost=proposal_data["cost"],
                confidence=proposal_data["confidence"],
                metadata=proposal_data.get("metadata", {})
            )

            self.proposals[task_id].append(proposal)
            logger.debug(
                f"[ContractNet] Proposal {proposal.proposal_id} received "
                f"for task {task_id}"
            )

    async def select_best_agent(
        self,
        task_id: str,
        strategy: str = "best_score"
    ) -> Optional[Proposal]:
        """
        최적 에이전트 선택

        Args:
            task_id: 작업 ID
            strategy: 선택 전략 ("best_score", "fastest", "most_confident")

        Returns:
            선택된 제안 또는 None
        """
        proposals = self.proposals.get(task_id, [])

        if not proposals:
            logger.warning(f"[ContractNet] No proposals for task {task_id}")
            return None

        if strategy == "best_score":
            selected = min(proposals, key=lambda p: p.score())
        elif strategy == "fastest":
            selected = min(proposals, key=lambda p: p.estimated_time)
        elif strategy == "most_confident":
            selected = max(proposals, key=lambda p: p.confidence)
        else:
            logger.warning(f"[ContractNet] Unknown strategy: {strategy}, using best_score")
            selected = min(proposals, key=lambda p: p.score())

        logger.info(
            f"[ContractNet] Selected agent {selected.agent_id} "
            f"for task {task_id} (score: {selected.score():.2f})"
        )

        return selected

    async def assign_task(
        self,
        task_id: str,
        selected_proposal: Proposal
    ):
        """
        작업 할당

        Args:
            task_id: 작업 ID
            selected_proposal: 선택된 제안
        """
        # 선택된 제안 수락
        selected_proposal.status = ProposalStatus.ACCEPTED

        # 다른 제안들은 거절
        for proposal in self.proposals.get(task_id, []):
            if proposal.proposal_id != selected_proposal.proposal_id:
                proposal.status = ProposalStatus.REJECTED

        # 작업 할당 이벤트
        await self.message_bus.publish(Event(
            event_id=f"assign-{task_id}",
            event_type=EventType.TASK_ASSIGNED,
            source="contract_net",
            data={
                "task_id": task_id,
                "assigned_to": selected_proposal.agent_id,
                "proposal_id": selected_proposal.proposal_id
            }
        ))

        logger.info(
            f"[ContractNet] Task {task_id} assigned to {selected_proposal.agent_id}"
        )

    async def negotiate_task(
        self,
        announcement: TaskAnnouncement,
        wait_time: float = 5.0,
        selection_strategy: str = "best_score"
    ) -> Optional[str]:
        """
        작업 협상 전체 프로세스

        Args:
            announcement: 작업 공고
            wait_time: 제안 대기 시간
            selection_strategy: 선택 전략

        Returns:
            할당된 에이전트 ID 또는 None
        """
        # 1. 작업 공고
        proposals = await self.announce_task(announcement, wait_time)

        if not proposals:
            logger.warning(f"[ContractNet] No proposals received for {announcement.task_id}")
            return None

        # 2. 최적 에이전트 선택
        selected = await self.select_best_agent(announcement.task_id, selection_strategy)

        if not selected:
            return None

        # 3. 작업 할당
        await self.assign_task(announcement.task_id, selected)

        return selected.agent_id


class CollaborationProtocol:
    """
    에이전트 협력 프로토콜

    Features:
    - Contract Net을 사용한 작업 할당
    - 1:1 협력 요청
    - 그룹 협력 (여러 에이전트 동시 협력)
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        registry: Optional[DistributedAgentRegistry] = None
    ):
        self.message_bus = message_bus
        self.registry = registry
        self.contract_net = ContractNetProtocol(message_bus, registry)

        self.initialized = False

    async def initialize(self):
        """프로토콜 초기화"""
        if self.initialized:
            return

        logger.info("[Collaboration] Initializing collaboration protocol...")

        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        if self.registry is None:
            self.registry = await get_agent_registry()

        await self.contract_net.initialize()

        self.initialized = True
        logger.info("[Collaboration] Collaboration protocol initialized")

    async def request_help(
        self,
        requester_id: str,
        capability: AgentCapability,
        context: Dict[str, Any],
        timeout: float = 30.0
    ) -> Optional[Dict[str, Any]]:
        """
        1:1 협력 요청

        Args:
            requester_id: 요청자 ID
            capability: 필요한 능력
            context: 컨텍스트 데이터
            timeout: 타임아웃

        Returns:
            응답 데이터 또는 None
        """
        logger.info(
            f"[Collaboration] Agent {requester_id} requesting help "
            f"for {capability.value}"
        )

        # 협력 요청 이벤트
        request_event = Event(
            event_id=f"help-req-{uuid.uuid4().hex[:8]}",
            event_type=EventType.COLLABORATION_REQUEST,
            source=requester_id,
            data={
                "required_capability": capability.value,
                "requester": requester_id,
                "context": context
            }
        )

        # 응답 대기
        response_event = await self.message_bus.request(request_event, timeout=timeout)

        if response_event:
            logger.info(f"[Collaboration] Help request answered by {response_event.source}")
            return response_event.data
        else:
            logger.warning(f"[Collaboration] Help request timed out")
            return None

    async def delegate_task(
        self,
        task_description: str,
        required_capability: AgentCapability,
        requester_id: str,
        wait_time: float = 5.0,
        **kwargs
    ) -> Optional[str]:
        """
        작업 위임 (Contract Net 사용)

        Args:
            task_description: 작업 설명
            required_capability: 필요한 능력
            requester_id: 요청자 ID
            wait_time: 제안 대기 시간
            **kwargs: 추가 제약사항

        Returns:
            할당된 에이전트 ID 또는 None
        """
        logger.info(
            f"[Collaboration] Delegating task requiring {required_capability.value}"
        )

        # 작업 공고 생성
        announcement = TaskAnnouncement(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            description=task_description,
            required_capability=required_capability,
            requester=requester_id,
            constraints=kwargs
        )

        # Contract Net으로 협상
        assigned_agent = await self.contract_net.negotiate_task(
            announcement,
            wait_time=wait_time
        )

        return assigned_agent

    async def form_team(
        self,
        capabilities: List[AgentCapability],
        requester_id: str,
        min_agents: Optional[int] = None
    ) -> Dict[AgentCapability, List[str]]:
        """
        팀 구성 (여러 능력을 가진 에이전트들 모집)

        Args:
            capabilities: 필요한 능력 리스트
            requester_id: 요청자 ID
            min_agents: 최소 필요 에이전트 수 (능력당)

        Returns:
            능력별 에이전트 ID 리스트
        """
        logger.info(
            f"[Collaboration] Forming team with capabilities: "
            f"{[c.value for c in capabilities]}"
        )

        team = {}

        for capability in capabilities:
            # 능력을 가진 에이전트들 찾기
            candidates = await self.registry.discover_by_capability(
                capability,
                status=AgentStatus.AVAILABLE
            )

            if min_agents and len(candidates) < min_agents:
                logger.warning(
                    f"[Collaboration] Not enough agents with {capability.value} "
                    f"(found {len(candidates)}, need {min_agents})"
                )
                team[capability] = []
            else:
                team[capability] = [agent.agent_id for agent in candidates]

        logger.info(
            f"[Collaboration] Team formed: "
            f"{sum(len(agents) for agents in team.values())} agents total"
        )

        return team

    async def broadcast_collaboration(
        self,
        requester_id: str,
        message: str,
        data: Dict[str, Any]
    ):
        """
        협력 브로드캐스트 (모든 에이전트에게 알림)

        Args:
            requester_id: 요청자 ID
            message: 메시지
            data: 데이터
        """
        logger.info(f"[Collaboration] Broadcasting collaboration from {requester_id}")

        await self.message_bus.publish(Event(
            event_id=f"broadcast-{uuid.uuid4().hex[:8]}",
            event_type=EventType.COLLABORATION_REQUEST,
            source=requester_id,
            data={
                "broadcast": True,
                "message": message,
                "data": data
            }
        ))


# 전역 협력 프로토콜 싱글톤
_collaboration_protocol: Optional[CollaborationProtocol] = None


async def get_collaboration_protocol() -> CollaborationProtocol:
    """전역 협력 프로토콜 인스턴스 가져오기"""
    global _collaboration_protocol

    if _collaboration_protocol is None:
        _collaboration_protocol = CollaborationProtocol()
        await _collaboration_protocol.initialize()

    return _collaboration_protocol
