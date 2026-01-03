"""
계층적 상태 관리 시스템

전역 상태(AgentState)와 에이전트별 로컬 상태를 분리하여 관리.
에이전트 간 선택적 상태 공유 지원.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from copy import deepcopy

from ..state import AgentState
from .message_bus import MessageBus, Event, EventType, get_message_bus

logger = logging.getLogger(__name__)


@dataclass
class AgentLocalState:
    """에이전트 로컬 상태"""
    agent_id: str
    agent_name: str

    # 에이전트 컨텍스트
    context: Dict[str, Any] = field(default_factory=dict)

    # 에이전트 캐시 (중간 결과 등)
    cache: Dict[str, Any] = field(default_factory=dict)

    # 작업 진행률 (0.0 ~ 1.0)
    progress: float = 0.0

    # 현재 작업
    current_task: Optional[str] = None

    # 다른 에이전트로부터 공유받은 데이터
    shared_data: Dict[str, Any] = field(default_factory=dict)

    # 상태 메타데이터
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def update(self, **kwargs):
        """상태 업데이트"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "context": self.context,
            "cache": self.cache,
            "progress": self.progress,
            "current_task": self.current_task,
            "shared_data": self.shared_data,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class HierarchicalStateManager:
    """
    계층적 상태 관리자

    Features:
    - 전역 상태 (AgentState) 관리
    - 에이전트별 로컬 상태 관리
    - 에이전트 간 선택적 상태 공유
    - 이벤트 기반 상태 업데이트 알림
    - 상태 스냅샷 및 복원
    """

    def __init__(
        self,
        global_state: Optional[AgentState] = None,
        message_bus: Optional[MessageBus] = None
    ):
        # 전역 상태
        self.global_state: Optional[AgentState] = global_state

        # 에이전트별 로컬 상태
        self.local_states: Dict[str, AgentLocalState] = {}

        # 메시지 버스
        self.message_bus = message_bus

        # 상태 변경 리스너
        self.state_change_listeners: List[callable] = []

        # 상태 스냅샷 (복원용)
        self.snapshots: Dict[str, Any] = {}

        self.initialized = False

    async def initialize(self):
        """상태 관리자 초기화"""
        if self.initialized:
            return

        logger.info("[StateManager] Initializing state manager...")

        # 메시지 버스 초기화
        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        # 이벤트 리스너 등록
        await self._setup_event_listeners()

        self.initialized = True
        logger.info("[StateManager] State manager initialized")

    async def _setup_event_listeners(self):
        """이벤트 리스너 설정"""
        await self.message_bus.subscribe(
            EventType.STATE_UPDATED,
            self._handle_state_update
        )
        await self.message_bus.subscribe(
            EventType.STATE_SHARED,
            self._handle_state_shared
        )

    async def set_global_state(self, state: AgentState):
        """전역 상태 설정"""
        self.global_state = state
        logger.debug("[StateManager] Global state updated")

        # 상태 업데이트 이벤트 발행
        await self.message_bus.publish(Event(
            event_id=f"state-{datetime.now().timestamp()}",
            event_type=EventType.STATE_UPDATED,
            source="state_manager",
            data={
                "state_type": "global",
                "session_id": state.get("session_id"),
                "user_id": state.get("user_id")
            }
        ))

    async def get_global_state(self) -> Optional[AgentState]:
        """전역 상태 조회"""
        return self.global_state

    async def update_global_state(self, updates: Dict[str, Any]):
        """전역 상태 부분 업데이트"""
        if self.global_state:
            self.global_state.update(updates)
            logger.debug(f"[StateManager] Global state updated with keys: {list(updates.keys())}")

            # 상태 업데이트 이벤트 발행
            await self.message_bus.publish(Event(
                event_id=f"state-{datetime.now().timestamp()}",
                event_type=EventType.STATE_UPDATED,
                source="state_manager",
                data={
                    "state_type": "global",
                    "updated_keys": list(updates.keys())
                }
            ))

    async def get_agent_state(self, agent_id: str) -> AgentLocalState:
        """
        에이전트 로컬 상태 조회 (없으면 생성)

        Args:
            agent_id: 에이전트 ID

        Returns:
            에이전트 로컬 상태
        """
        if agent_id not in self.local_states:
            logger.debug(f"[StateManager] Creating new local state for agent: {agent_id}")
            self.local_states[agent_id] = AgentLocalState(
                agent_id=agent_id,
                agent_name=agent_id  # 기본값, 나중에 업데이트 가능
            )

        return self.local_states[agent_id]

    async def update_agent_state(
        self,
        agent_id: str,
        updates: Dict[str, Any],
        broadcast: bool = False
    ):
        """
        에이전트 로컬 상태 업데이트

        Args:
            agent_id: 에이전트 ID
            updates: 업데이트할 필드들
            broadcast: 다른 에이전트들에게 알림 여부
        """
        state = await self.get_agent_state(agent_id)
        state.update(**updates)

        logger.debug(f"[StateManager] Agent {agent_id} state updated")

        if broadcast:
            # 상태 업데이트 이벤트 발행
            await self.message_bus.publish(Event(
                event_id=f"state-{agent_id}-{datetime.now().timestamp()}",
                event_type=EventType.STATE_UPDATED,
                source=agent_id,
                data={
                    "state_type": "local",
                    "agent_id": agent_id,
                    "updates": updates
                }
            ))

    async def share_state(
        self,
        from_agent: str,
        to_agent: str,
        data: Dict[str, Any],
        key: Optional[str] = None
    ):
        """
        에이전트 간 상태 공유

        Args:
            from_agent: 공유하는 에이전트 ID
            to_agent: 받는 에이전트 ID
            data: 공유할 데이터
            key: 데이터를 저장할 키 (기본값: from_agent)
        """
        to_state = await self.get_agent_state(to_agent)
        storage_key = key or from_agent

        to_state.shared_data[storage_key] = {
            "data": data,
            "from": from_agent,
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"[StateManager] State shared from {from_agent} to {to_agent}")

        # 상태 공유 이벤트 발행
        await self.message_bus.publish(Event(
            event_id=f"share-{from_agent}-{to_agent}-{datetime.now().timestamp()}",
            event_type=EventType.STATE_SHARED,
            source=from_agent,
            data={
                "from_agent": from_agent,
                "to_agent": to_agent,
                "key": storage_key
            }
        ))

    async def get_shared_data(
        self,
        agent_id: str,
        from_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        공유받은 데이터 조회

        Args:
            agent_id: 조회하는 에이전트 ID
            from_agent: 특정 에이전트로부터 받은 데이터만 (선택적)

        Returns:
            공유받은 데이터
        """
        state = await self.get_agent_state(agent_id)

        if from_agent:
            return state.shared_data.get(from_agent, {})

        return state.shared_data

    async def broadcast_state(
        self,
        from_agent: str,
        data: Dict[str, Any],
        to_all: bool = True
    ):
        """
        상태를 여러 에이전트에게 브로드캐스트

        Args:
            from_agent: 브로드캐스트하는 에이전트 ID
            data: 브로드캐스트할 데이터
            to_all: 모든 에이전트에게 (True) 또는 이벤트로만 발행 (False)
        """
        if to_all:
            # 모든 등록된 에이전트에게 직접 공유
            for agent_id in self.local_states.keys():
                if agent_id != from_agent:
                    await self.share_state(from_agent, agent_id, data)
        else:
            # 이벤트로만 발행 (구독자가 직접 처리)
            await self.message_bus.publish(Event(
                event_id=f"broadcast-{from_agent}-{datetime.now().timestamp()}",
                event_type=EventType.STATE_SHARED,
                source=from_agent,
                data={
                    "from_agent": from_agent,
                    "broadcast": True,
                    "data": data
                }
            ))

    async def create_snapshot(self, snapshot_id: str):
        """
        현재 상태의 스냅샷 생성

        Args:
            snapshot_id: 스냅샷 식별자
        """
        snapshot = {
            "global_state": deepcopy(self.global_state),
            "local_states": {
                agent_id: state.to_dict()
                for agent_id, state in self.local_states.items()
            },
            "timestamp": datetime.now().isoformat()
        }

        self.snapshots[snapshot_id] = snapshot
        logger.info(f"[StateManager] Snapshot created: {snapshot_id}")

    async def restore_snapshot(self, snapshot_id: str) -> bool:
        """
        스냅샷에서 상태 복원

        Args:
            snapshot_id: 복원할 스냅샷 식별자

        Returns:
            복원 성공 여부
        """
        if snapshot_id not in self.snapshots:
            logger.warning(f"[StateManager] Snapshot not found: {snapshot_id}")
            return False

        snapshot = self.snapshots[snapshot_id]

        # 전역 상태 복원
        self.global_state = snapshot["global_state"]

        # 로컬 상태 복원
        self.local_states = {}
        for agent_id, state_dict in snapshot["local_states"].items():
            self.local_states[agent_id] = AgentLocalState(
                agent_id=state_dict["agent_id"],
                agent_name=state_dict["agent_name"],
                context=state_dict["context"],
                cache=state_dict["cache"],
                progress=state_dict["progress"],
                current_task=state_dict["current_task"],
                shared_data=state_dict["shared_data"]
            )

        logger.info(f"[StateManager] Snapshot restored: {snapshot_id}")
        return True

    async def _handle_state_update(self, event: Event):
        """상태 업데이트 이벤트 핸들러"""
        # 상태 변경 리스너들에게 알림
        for listener in self.state_change_listeners:
            try:
                await listener(event)
            except Exception as e:
                logger.error(f"[StateManager] Error in state change listener: {e}")

    async def _handle_state_shared(self, event: Event):
        """상태 공유 이벤트 핸들러"""
        logger.debug(f"[StateManager] State shared event received from {event.source}")

    def add_state_change_listener(self, listener: callable):
        """상태 변경 리스너 추가"""
        self.state_change_listeners.append(listener)
        logger.debug("[StateManager] State change listener added")

    def get_all_agent_states(self) -> Dict[str, AgentLocalState]:
        """모든 에이전트 로컬 상태 조회"""
        return self.local_states

    def get_statistics(self) -> Dict[str, Any]:
        """상태 관리 통계"""
        return {
            "global_state_exists": self.global_state is not None,
            "local_states_count": len(self.local_states),
            "snapshots_count": len(self.snapshots),
            "agents": list(self.local_states.keys())
        }

    async def clear_agent_state(self, agent_id: str):
        """에이전트 로컬 상태 삭제"""
        if agent_id in self.local_states:
            del self.local_states[agent_id]
            logger.info(f"[StateManager] Agent state cleared: {agent_id}")

    async def close(self):
        """상태 관리자 종료"""
        logger.info("[StateManager] Closing state manager...")
        self.local_states.clear()
        self.snapshots.clear()
        self.state_change_listeners.clear()
        self.initialized = False
        logger.info("[StateManager] State manager closed")


# 전역 상태 관리자 싱글톤
_state_manager: Optional[HierarchicalStateManager] = None


async def get_state_manager() -> HierarchicalStateManager:
    """전역 상태 관리자 인스턴스 가져오기"""
    global _state_manager

    if _state_manager is None:
        _state_manager = HierarchicalStateManager()
        await _state_manager.initialize()

    return _state_manager
