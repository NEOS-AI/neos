"""
이벤트 기반 메시지 버스

에이전트 간 비동기 통신을 위한 Pub/Sub 메시지 버스.
기존 MessageQueueInterface를 활용하되, 이벤트 기반 아키텍처로 확장.
"""

import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

from neos.utils.message_queue import MessageQueueInterface, MessageQueueFactory
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """이벤트 타입 정의"""
    # Agent lifecycle
    AGENT_REGISTERED = "agent.registered"
    AGENT_UNREGISTERED = "agent.unregistered"
    AGENT_HEARTBEAT = "agent.heartbeat"
    AGENT_FAILED = "agent.failed"

    # Task management
    TASK_SUBMITTED = "task.submitted"
    TASK_ASSIGNED = "task.assigned"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STEP_COMPLETED = "workflow.step.completed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Search events
    SEARCH_REQUESTED = "search.requested"
    SEARCH_COMPLETED = "search.completed"
    SEARCH_RESULTS_AVAILABLE = "search.results.available"

    # Analysis events
    ANALYSIS_REQUESTED = "analysis.requested"
    ANALYSIS_COMPLETED = "analysis.completed"

    # Collaboration events
    COLLABORATION_REQUEST = "collaboration.request"
    COLLABORATION_RESPONSE = "collaboration.response"
    NEGOTIATION_STARTED = "negotiation.started"
    NEGOTIATION_COMPLETED = "negotiation.completed"

    # State events
    STATE_UPDATED = "state.updated"
    STATE_SHARED = "state.shared"


@dataclass
class Event:
    """이벤트 데이터 클래스"""
    event_id: str
    event_type: EventType
    source: str  # 이벤트를 발생시킨 에이전트/컴포넌트 이름
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None  # 관련 이벤트들을 연결
    reply_to: Optional[str] = None  # 응답을 받을 채널

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """딕셔너리에서 생성"""
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            source=data["source"],
            data=data["data"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            correlation_id=data.get("correlation_id"),
            reply_to=data.get("reply_to")
        )


EventHandler = Callable[[Event], Awaitable[None]]


class MessageBus:
    """
    이벤트 기반 메시지 버스

    Features:
    - Pub/Sub 패턴으로 에이전트 간 느슨한 결합
    - 이벤트 타입별 핸들러 등록
    - 요청-응답 패턴 지원 (RPC-like)
    - 이벤트 히스토리 추적
    - 와일드카드 구독 지원 (예: "agent.*")
    """

    def __init__(self, message_queue: Optional[MessageQueueInterface] = None):
        # 메시지 큐 백엔드 (Redis 또는 In-Memory)
        self.message_queue = message_queue or MessageQueueFactory.create(
            queue_type=settings.MESSAGE_QUEUE_TYPE if hasattr(settings, 'MESSAGE_QUEUE_TYPE') else "memory"
        )

        # 이벤트 핸들러 레지스트리
        self.handlers: Dict[str, List[EventHandler]] = {}

        # 요청-응답 대기 중인 요청들
        self.pending_requests: Dict[str, asyncio.Future] = {}

        # 이벤트 히스토리 (선택적)
        self.event_history: List[Event] = []
        self.max_history_size = 1000

        # 구독 중인 채널들
        self.subscribed_channels: Set[str] = set()

        self.initialized = False

    async def initialize(self):
        """메시지 버스 초기화"""
        if self.initialized:
            return

        logger.info("[MessageBus] Initializing message bus...")
        await self.message_queue.initialize()
        self.initialized = True
        logger.info("[MessageBus] Message bus initialized successfully")

    async def publish(self, event: Event) -> bool:
        """
        이벤트 발행

        Args:
            event: 발행할 이벤트

        Returns:
            성공 여부
        """
        if not self.initialized:
            await self.initialize()

        try:
            # 이벤트 히스토리에 추가
            self._add_to_history(event)

            # 채널 이름은 이벤트 타입
            channel = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type

            logger.debug(f"[MessageBus] Publishing event {event.event_id} to channel {channel}")

            # 메시지 큐에 발행
            success = await self.message_queue.publish(channel, event.to_dict())

            if success:
                logger.debug(f"[MessageBus] Event {event.event_id} published successfully")
            else:
                logger.error(f"[MessageBus] Failed to publish event {event.event_id}")

            return success

        except Exception as e:
            logger.error(f"[MessageBus] Error publishing event: {e}")
            return False

    async def subscribe(self, event_type: EventType, handler: EventHandler):
        """
        이벤트 타입 구독

        Args:
            event_type: 구독할 이벤트 타입
            handler: 이벤트 핸들러 함수
        """
        if not self.initialized:
            await self.initialize()

        channel = event_type.value if isinstance(event_type, EventType) else event_type

        # 핸들러 등록
        if channel not in self.handlers:
            self.handlers[channel] = []
        self.handlers[channel].append(handler)

        logger.info(f"[MessageBus] Handler registered for event type: {channel}")

        # 아직 구독하지 않은 채널이면 메시지 큐에 구독
        if channel not in self.subscribed_channels:
            await self.message_queue.subscribe(channel, self._handle_message)
            self.subscribed_channels.add(channel)
            logger.info(f"[MessageBus] Subscribed to channel: {channel}")

    async def _handle_message(self, message: Dict[str, Any]):
        """메시지 큐에서 받은 메시지 처리"""
        try:
            event = Event.from_dict(message)
            channel = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type

            logger.debug(f"[MessageBus] Received event {event.event_id} on channel {channel}")

            # 요청-응답 패턴 처리
            if event.correlation_id and event.correlation_id in self.pending_requests:
                future = self.pending_requests[event.correlation_id]
                if not future.done():
                    future.set_result(event)
                del self.pending_requests[event.correlation_id]
                logger.debug(f"[MessageBus] Resolved pending request {event.correlation_id}")
                return

            # 등록된 핸들러들 실행
            if channel in self.handlers:
                handler_tasks = [
                    handler(event) for handler in self.handlers[channel]
                ]
                await asyncio.gather(*handler_tasks, return_exceptions=True)
                logger.debug(f"[MessageBus] Executed {len(handler_tasks)} handlers for event {event.event_id}")

        except Exception as e:
            logger.error(f"[MessageBus] Error handling message: {e}", exc_info=True)

    async def request(
        self,
        event: Event,
        timeout: float = 30.0
    ) -> Optional[Event]:
        """
        요청-응답 패턴 (RPC-like)

        Args:
            event: 요청 이벤트
            timeout: 타임아웃 (초)

        Returns:
            응답 이벤트 또는 None (타임아웃)
        """
        if not self.initialized:
            await self.initialize()

        # 응답을 받을 correlation_id 설정
        request_id = str(uuid.uuid4())
        event.correlation_id = request_id

        # Future 생성하여 응답 대기
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future

        try:
            # 이벤트 발행
            await self.publish(event)

            # 응답 대기
            logger.debug(f"[MessageBus] Waiting for response to request {request_id}")
            response = await asyncio.wait_for(future, timeout=timeout)
            logger.debug(f"[MessageBus] Received response to request {request_id}")
            return response

        except asyncio.TimeoutError:
            logger.warning(f"[MessageBus] Request {request_id} timed out after {timeout}s")
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]
            return None
        except Exception as e:
            logger.error(f"[MessageBus] Error in request-response: {e}")
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]
            return None

    async def reply(self, original_event: Event, reply_data: Dict[str, Any], source: str):
        """
        요청에 대한 응답 전송

        Args:
            original_event: 원본 요청 이벤트
            reply_data: 응답 데이터
            source: 응답을 보내는 에이전트 이름
        """
        if not original_event.correlation_id:
            logger.warning("[MessageBus] Cannot reply to event without correlation_id")
            return

        # 응답 이벤트 생성
        reply_event = Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.COLLABORATION_RESPONSE,
            source=source,
            data=reply_data,
            correlation_id=original_event.correlation_id
        )

        # 원래 이벤트 타입 채널에 발행 (응답이 원래 채널로 전달됨)
        await self.publish(reply_event)

    def _add_to_history(self, event: Event):
        """이벤트 히스토리에 추가"""
        self.event_history.append(event)

        # 최대 크기 초과 시 오래된 이벤트 제거
        if len(self.event_history) > self.max_history_size:
            self.event_history = self.event_history[-self.max_history_size:]

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        이벤트 히스토리 조회

        Args:
            event_type: 필터링할 이벤트 타입
            source: 필터링할 소스
            limit: 최대 반환 개수

        Returns:
            필터링된 이벤트 리스트
        """
        filtered = self.event_history

        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]

        if source:
            filtered = [e for e in filtered if e.source == source]

        return filtered[-limit:]

    async def unsubscribe(self, event_type: EventType):
        """이벤트 타입 구독 해제"""
        channel = event_type.value if isinstance(event_type, EventType) else event_type

        if channel in self.handlers:
            del self.handlers[channel]

        if channel in self.subscribed_channels:
            await self.message_queue.unsubscribe(channel)
            self.subscribed_channels.remove(channel)
            logger.info(f"[MessageBus] Unsubscribed from channel: {channel}")

    async def close(self):
        """메시지 버스 종료"""
        logger.info("[MessageBus] Closing message bus...")

        # 모든 구독 해제
        for channel in list(self.subscribed_channels):
            await self.message_queue.unsubscribe(channel)

        # 메시지 큐 종료
        await self.message_queue.close()

        self.initialized = False
        logger.info("[MessageBus] Message bus closed")


# 전역 메시지 버스 싱글톤
_message_bus: Optional[MessageBus] = None


async def get_message_bus() -> MessageBus:
    """전역 메시지 버스 인스턴스 가져오기"""
    global _message_bus

    if _message_bus is None:
        _message_bus = MessageBus()
        await _message_bus.initialize()

    return _message_bus
