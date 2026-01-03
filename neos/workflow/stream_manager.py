"""
SSE Stream Manager - 재연결 지원 및 이벤트 버퍼링

Phase 3 Item 3: SSE 스트리밍 개선
- Last-Event-ID를 통한 재연결 지원
- 이벤트 버퍼링 및 재전송
- 연결 상태 관리 및 자동 정리
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """SSE 이벤트 데이터 구조"""
    id: str
    event: str
    data: str
    timestamp: float = field(default_factory=time.time)
    retry: Optional[int] = None  # 재연결 간격 (ms)

    def to_sse_format(self) -> str:
        """SSE 프로토콜 형식으로 변환"""
        lines = []

        if self.id:
            lines.append(f"id: {self.id}")

        if self.event:
            lines.append(f"event: {self.event}")

        if self.retry is not None:
            lines.append(f"retry: {self.retry}")

        # data는 여러 줄일 수 있으므로 각 줄마다 "data: " 접두사 추가
        for line in self.data.split('\n'):
            lines.append(f"data: {line}")

        # SSE 형식: 빈 줄로 이벤트 구분
        lines.append('')
        lines.append('')

        return '\n'.join(lines)


@dataclass
class StreamSession:
    """스트림 세션 정보"""
    session_id: str
    user_id: Optional[str]
    created_at: datetime
    last_activity: datetime
    event_buffer: deque  # StreamEvent 객체들
    queue: asyncio.Queue
    active_connections: int = 0
    last_event_id: int = 0

    def is_expired(self, ttl_seconds: int = 300) -> bool:
        """세션 만료 여부 확인 (기본 5분)"""
        return (datetime.utcnow() - self.last_activity).total_seconds() > ttl_seconds


class StreamManager:
    """
    SSE 스트림 관리자

    기능:
    - 재연결 시 Last-Event-ID부터 이벤트 재전송
    - 세션별 이벤트 버퍼링 (메모리 효율적)
    - 비활성 세션 자동 정리
    - 멀티 클라이언트 지원 (동일 세션에 여러 연결)
    """

    def __init__(
        self,
        buffer_size: int = 100,
        session_ttl: int = 300,  # 5분
        cleanup_interval: int = 60  # 1분마다 정리
    ):
        """
        Args:
            buffer_size: 세션당 보관할 최대 이벤트 수
            session_ttl: 세션 만료 시간 (초)
            cleanup_interval: 세션 정리 간격 (초)
        """
        self.buffer_size = buffer_size
        self.session_ttl = session_ttl
        self.cleanup_interval = cleanup_interval

        # 세션 ID -> StreamSession
        self._sessions: Dict[str, StreamSession] = {}

        # 정리 태스크
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """백그라운드 정리 태스크 시작"""
        if self._running:
            logger.warning("StreamManager already running")
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("StreamManager started")

    async def stop(self):
        """백그라운드 태스크 중지 및 정리"""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 모든 세션 정리
        self._sessions.clear()
        logger.info("StreamManager stopped")

    def create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> StreamSession:
        """새 스트림 세션 생성 또는 기존 세션 반환"""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.last_activity = datetime.utcnow()
            session.active_connections += 1
            logger.info(f"Reusing session {session_id}, connections: {session.active_connections}")
            return session

        session = StreamSession(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
            event_buffer=deque(maxlen=self.buffer_size),
            queue=asyncio.Queue(),
            active_connections=1,
            last_event_id=0
        )

        self._sessions[session_id] = session
        logger.info(f"Created new session {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[StreamSession]:
        """세션 조회"""
        return self._sessions.get(session_id)

    async def add_event(
        self,
        session_id: str,
        event: str,
        data: Any,
        retry: Optional[int] = None
    ) -> bool:
        """
        세션에 이벤트 추가

        Args:
            session_id: 세션 ID
            event: 이벤트 타입
            data: 이벤트 데이터 (dict 또는 str)
            retry: 재연결 간격 (ms, 선택)

        Returns:
            bool: 성공 여부
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return False

        # 이벤트 ID 생성
        session.last_event_id += 1
        event_id = str(session.last_event_id)

        # 데이터 직렬화
        if isinstance(data, dict):
            import json
            data_str = json.dumps(data, ensure_ascii=False)
        else:
            data_str = str(data)

        # StreamEvent 생성
        stream_event = StreamEvent(
            id=event_id,
            event=event,
            data=data_str,
            retry=retry
        )

        # 버퍼에 추가 (deque는 maxlen 설정 시 자동으로 오래된 항목 제거)
        session.event_buffer.append(stream_event)

        # 큐에 추가 (실시간 스트리밍)
        try:
            await session.queue.put(stream_event)
            session.last_activity = datetime.utcnow()
            return True
        except Exception as e:
            logger.error(f"Failed to add event to session {session_id}: {e}")
            return False

    def get_events_since(
        self,
        session_id: str,
        last_event_id: Optional[str] = None
    ) -> List[StreamEvent]:
        """
        Last-Event-ID 이후의 이벤트 반환 (재연결 지원)

        Args:
            session_id: 세션 ID
            last_event_id: 클라이언트가 마지막으로 받은 이벤트 ID

        Returns:
            List[StreamEvent]: 재전송할 이벤트 리스트
        """
        session = self.get_session(session_id)
        if not session:
            return []

        if last_event_id is None:
            # 첫 연결: 버퍼의 모든 이벤트 반환 (선택적)
            return list(session.event_buffer)

        try:
            last_id = int(last_event_id)
        except ValueError:
            logger.warning(f"Invalid last_event_id: {last_event_id}")
            return []

        # last_id 이후의 이벤트만 필터링
        events = []
        for event in session.event_buffer:
            try:
                if int(event.id) > last_id:
                    events.append(event)
            except ValueError:
                continue

        logger.info(f"Reconnection: sending {len(events)} missed events to session {session_id}")
        return events

    def disconnect(self, session_id: str):
        """연결 종료 (활성 연결 수 감소)"""
        session = self.get_session(session_id)
        if session:
            session.active_connections = max(0, session.active_connections - 1)
            session.last_activity = datetime.utcnow()
            logger.info(f"Disconnected from session {session_id}, remaining connections: {session.active_connections}")

    def remove_session(self, session_id: str):
        """세션 강제 제거"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Removed session {session_id}")

    async def _cleanup_loop(self):
        """만료된 세션 정리 루프"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_expired_sessions(self):
        """만료된 세션 제거"""
        now = datetime.utcnow()
        expired_sessions = []

        for session_id, session in self._sessions.items():
            # 활성 연결이 있으면 유지
            if session.active_connections > 0:
                continue

            # 만료 확인
            if session.is_expired(self.session_ttl):
                expired_sessions.append(session_id)

        # 만료된 세션 제거
        for session_id in expired_sessions:
            del self._sessions[session_id]
            logger.info(f"Cleaned up expired session {session_id}")

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환"""
        total_connections = sum(s.active_connections for s in self._sessions.values())
        total_buffered_events = sum(len(s.event_buffer) for s in self._sessions.values())

        return {
            "total_sessions": len(self._sessions),
            "active_connections": total_connections,
            "total_buffered_events": total_buffered_events,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "active_connections": s.active_connections,
                    "buffered_events": len(s.event_buffer),
                    "last_activity": s.last_activity.isoformat(),
                    "age_seconds": (datetime.utcnow() - s.created_at).total_seconds()
                }
                for s in self._sessions.values()
            ]
        }


# 전역 StreamManager 인스턴스
stream_manager = StreamManager(
    buffer_size=100,  # 세션당 최대 100개 이벤트 보관
    session_ttl=300,  # 5분 후 만료
    cleanup_interval=60  # 1분마다 정리
)
