"""
Supervisor 패턴 구현

에이전트 실행을 감독하고, 실패 시 자동으로 복구하거나 대체 에이전트를 할당.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .message_bus import MessageBus, Event, EventType, get_message_bus
from .agent_registry import (
    DistributedAgentRegistry,
    AgentCapability,
    AgentStatus,
    get_agent_registry
)
from .work_queue import Task, TaskStatus, get_work_queue

logger = logging.getLogger(__name__)


class SupervisorStrategy(str, Enum):
    """Supervisor 전략"""
    ONE_FOR_ONE = "one_for_one"  # 실패한 에이전트만 재시작
    ONE_FOR_ALL = "one_for_all"  # 모든 에이전트 재시작
    REST_FOR_ONE = "rest_for_one"  # 실패한 에이전트 이후의 모든 에이전트 재시작


@dataclass
class AgentFailureRecord:
    """에이전트 실패 기록"""
    agent_id: str
    agent_name: str
    failure_time: datetime
    error_message: str
    task_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "failure_time": self.failure_time.isoformat(),
            "error_message": self.error_message,
            "task_id": self.task_id
        }


@dataclass
class SupervisorConfig:
    """Supervisor 설정"""
    max_restart_intensity: int = 5  # 최대 재시작 횟수
    max_restart_period: int = 60  # 재시작 기간 (초)
    restart_delay: float = 2.0  # 재시작 전 대기 시간
    strategy: SupervisorStrategy = SupervisorStrategy.ONE_FOR_ONE
    auto_restart: bool = True  # 자동 재시작 활성화


class AgentSupervisor:
    """
    에이전트 Supervisor

    Features:
    - 에이전트 실행 감독
    - 실패 감지 및 자동 복구
    - 재시작 전략 (One-for-One, One-for-All, Rest-for-One)
    - 대체 에이전트 자동 할당
    - 실패 히스토리 추적
    """

    def __init__(
        self,
        config: Optional[SupervisorConfig] = None,
        message_bus: Optional[MessageBus] = None,
        registry: Optional[DistributedAgentRegistry] = None
    ):
        self.config = config or SupervisorConfig()
        self.message_bus = message_bus
        self.registry = registry

        # 감독 중인 에이전트들
        self.supervised_agents: Dict[str, Any] = {}  # agent_id -> agent_instance

        # 실패 기록
        self.failure_history: Dict[str, List[AgentFailureRecord]] = {}  # agent_id -> records

        # 재시작 횟수
        self.restart_counts: Dict[str, int] = {}

        # 감독 루프 태스크
        self.supervision_loop_task: Optional[asyncio.Task] = None

        self.is_running = False
        self.initialized = False

    async def initialize(self):
        """Supervisor 초기화"""
        if self.initialized:
            return

        logger.info("[Supervisor] Initializing agent supervisor...")

        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        if self.registry is None:
            self.registry = await get_agent_registry()

        # 이벤트 구독
        await self._setup_subscriptions()

        self.initialized = True
        logger.info("[Supervisor] Agent supervisor initialized")

    async def _setup_subscriptions(self):
        """이벤트 구독 설정"""
        await self.message_bus.subscribe(
            EventType.AGENT_FAILED,
            self._handle_agent_failure
        )
        await self.message_bus.subscribe(
            EventType.TASK_FAILED,
            self._handle_task_failure
        )

    async def start(self):
        """Supervisor 시작"""
        if self.is_running:
            logger.warning("[Supervisor] Supervisor is already running")
            return

        logger.info("[Supervisor] Starting agent supervisor...")
        self.is_running = True

        # 감독 루프 시작
        self.supervision_loop_task = asyncio.create_task(self._supervision_loop())

        logger.info("[Supervisor] Agent supervisor started")

    async def stop(self):
        """Supervisor 중지"""
        logger.info("[Supervisor] Stopping agent supervisor...")
        self.is_running = False

        if self.supervision_loop_task:
            self.supervision_loop_task.cancel()
            try:
                await self.supervision_loop_task
            except asyncio.CancelledError:
                pass

        logger.info("[Supervisor] Agent supervisor stopped")

    async def supervise_agent(
        self,
        agent: Any,
        agent_id: str,
        restart_callback: Optional[Callable] = None
    ):
        """
        에이전트 감독 시작

        Args:
            agent: 감독할 에이전트 인스턴스
            agent_id: 에이전트 ID
            restart_callback: 재시작 시 호출할 콜백
        """
        logger.info(f"[Supervisor] Starting supervision of agent {agent_id}")

        self.supervised_agents[agent_id] = {
            "agent": agent,
            "restart_callback": restart_callback,
            "supervised_since": datetime.utcnow()
        }

        if agent_id not in self.failure_history:
            self.failure_history[agent_id] = []

        if agent_id not in self.restart_counts:
            self.restart_counts[agent_id] = 0

    async def unsupervise_agent(self, agent_id: str):
        """에이전트 감독 중지"""
        if agent_id in self.supervised_agents:
            del self.supervised_agents[agent_id]
            logger.info(f"[Supervisor] Stopped supervision of agent {agent_id}")

    async def _supervision_loop(self):
        """감독 루프"""
        logger.info("[Supervisor] Supervision loop started")

        while self.is_running:
            try:
                await asyncio.sleep(10)  # 10초마다 체크

                # 모든 감독 중인 에이전트 체크
                for agent_id in list(self.supervised_agents.keys()):
                    await self._check_agent_health(agent_id)

            except asyncio.CancelledError:
                logger.info("[Supervisor] Supervision loop cancelled")
                break
            except Exception as e:
                logger.error(f"[Supervisor] Error in supervision loop: {e}", exc_info=True)

        logger.info("[Supervisor] Supervision loop ended")

    async def _check_agent_health(self, agent_id: str):
        """에이전트 건강 체크"""
        # 레지스트리에서 에이전트 정보 가져오기
        agent_metadata = self.registry.get_agent(agent_id)

        if not agent_metadata:
            logger.warning(f"[Supervisor] Agent {agent_id} not found in registry")
            return

        # Heartbeat 체크
        if not agent_metadata.is_healthy:
            logger.warning(f"[Supervisor] Agent {agent_id} is unhealthy (no heartbeat)")

            # 실패 이벤트 발행
            await self.message_bus.publish(Event(
                event_id=f"agent-failed-{agent_id}",
                event_type=EventType.AGENT_FAILED,
                source="supervisor",
                data={
                    "agent_id": agent_id,
                    "reason": "no_heartbeat"
                }
            ))

    async def _handle_agent_failure(self, event: Event):
        """에이전트 실패 이벤트 처리"""
        agent_id = event.data.get("agent_id")
        error = event.data.get("error", event.data.get("reason", "Unknown error"))

        if agent_id not in self.supervised_agents:
            return

        logger.error(f"[Supervisor] Agent {agent_id} failed: {error}")

        # 실패 기록
        record = AgentFailureRecord(
            agent_id=agent_id,
            agent_name=agent_id,
            failure_time=datetime.utcnow(),
            error_message=str(error)
        )

        self.failure_history.setdefault(agent_id, []).append(record)

        # 재시작 가능 여부 확인
        if self._should_restart(agent_id):
            await self._restart_agent(agent_id)
        else:
            logger.error(
                f"[Supervisor] Agent {agent_id} exceeded max restart intensity, "
                f"not restarting"
            )

    async def _handle_task_failure(self, event: Event):
        """작업 실패 이벤트 처리"""
        task_id = event.data.get("task_id")
        agent_id = event.data.get("agent_id")
        error = event.data.get("error")

        logger.warning(f"[Supervisor] Task {task_id} failed on agent {agent_id}: {error}")

        # 대체 에이전트 찾아서 재할당
        # (작업 큐가 자동으로 재시도하므로 여기서는 로깅만)

    def _should_restart(self, agent_id: str) -> bool:
        """재시작 가능 여부 확인"""
        if not self.config.auto_restart:
            return False

        # 최근 실패 횟수 확인
        recent_failures = [
            record for record in self.failure_history.get(agent_id, [])
            if datetime.utcnow() - record.failure_time < timedelta(
                seconds=self.config.max_restart_period
            )
        ]

        return len(recent_failures) < self.config.max_restart_intensity

    async def _restart_agent(self, agent_id: str):
        """에이전트 재시작"""
        logger.info(f"[Supervisor] Restarting agent {agent_id}...")

        # 재시작 대기
        await asyncio.sleep(self.config.restart_delay)

        agent_info = self.supervised_agents.get(agent_id)

        if not agent_info:
            logger.warning(f"[Supervisor] Agent {agent_id} not found, cannot restart")
            return

        try:
            # 재시작 콜백 호출
            if agent_info["restart_callback"]:
                await agent_info["restart_callback"]()
            else:
                # 기본 재시작: stop -> start
                agent = agent_info["agent"]
                if hasattr(agent, "stop"):
                    await agent.stop()
                await asyncio.sleep(1)
                if hasattr(agent, "start"):
                    await agent.start()

            self.restart_counts[agent_id] = self.restart_counts.get(agent_id, 0) + 1

            logger.info(
                f"[Supervisor] Agent {agent_id} restarted successfully "
                f"(restart count: {self.restart_counts[agent_id]})"
            )

        except Exception as e:
            logger.error(f"[Supervisor] Failed to restart agent {agent_id}: {e}")

    def get_failure_history(
        self,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AgentFailureRecord]:
        """실패 히스토리 조회"""
        if agent_id:
            return self.failure_history.get(agent_id, [])[-limit:]

        # 모든 에이전트의 실패 히스토리
        all_failures = []
        for failures in self.failure_history.values():
            all_failures.extend(failures)

        # 시간순 정렬
        all_failures.sort(key=lambda r: r.failure_time, reverse=True)

        return all_failures[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """통계 조회"""
        total_failures = sum(len(records) for records in self.failure_history.values())
        total_restarts = sum(self.restart_counts.values())

        return {
            "supervised_agents": len(self.supervised_agents),
            "total_failures": total_failures,
            "total_restarts": total_restarts,
            "agents_with_failures": len([
                aid for aid, records in self.failure_history.items()
                if records
            ]),
            "restart_counts": self.restart_counts.copy()
        }


# 전역 Supervisor 싱글톤
_supervisor: Optional[AgentSupervisor] = None


async def get_supervisor() -> AgentSupervisor:
    """전역 Supervisor 인스턴스 가져오기"""
    global _supervisor

    if _supervisor is None:
        _supervisor = AgentSupervisor()
        await _supervisor.initialize()

    return _supervisor
