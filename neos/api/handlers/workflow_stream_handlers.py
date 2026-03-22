"""
Workflow Streaming API handlers - SSE & WebSocket 기반 실시간 스트리밍

이벤트 로깅 아키텍처 (DI 패턴):
---------------------------------
이 모듈은 Dependency Injection 패턴을 사용하여 워크플로우 이벤트를 실시간으로 스트리밍합니다.

1. WorkflowStreamCallback (WorkflowEventHandler 구현):
   - 워크플로우 이벤트를 수신하여 스트림 큐에 추가
   - 선택적으로 DB에 영구 저장 (enable_db_logging=True)
   - Observer 패턴을 통해 워크플로우와 느슨한 결합 유지

2. Dependency Injection:
   - multi_agent_workflow.execute_workflow(event_handler=callback)
   - 워크플로우가 각 단계에서 자동으로 이벤트 발생
   - 핸들러가 이벤트를 받아 스트림 & DB 저장 처리

3. 스트리밍 방식:
   - SSE: 단방향, 자동 재연결, HTTP 기반
   - WebSocket: 양방향, 낮은 지연시간, 실시간 통신

이 설계는 unified_handlers.py의 패턴을 따릅니다.
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Dict, Any, Optional, Callable
from datetime import datetime
import json
import asyncio
import uuid

from neos.api.models.query_models import (
    WorkflowStreamRequest,
    WorkflowStreamEvent,
    WorkflowStreamEventType
)
from neos.api.services.query_service import QueryService
from neos.workflow.graph import multi_agent_workflow
from neos.workflow.events import WorkflowEventHandler
from neos.workflow.stream_manager import stream_manager
from neos.config.settings import settings
from neos.utils.logger import get_logger
from neos.database.connection import db_manager

logger = get_logger(__name__)
router = APIRouter()


class WorkflowStreamCallback(WorkflowEventHandler):
    """
    워크플로우 실행 중 스트리밍 이벤트를 수집하는 콜백

    WorkflowEventHandler 인터페이스를 구현하여 DI 패턴 지원
    이벤트를 스트림 큐에 추가하고 선택적으로 DB에 저장
    """

    def __init__(
        self,
        session_id: str,
        event_queue: asyncio.Queue,
        enable_db_logging: bool = False,
        user_id: Optional[str] = None
    ):
        self.session_id = session_id
        self.event_queue = event_queue
        self.start_time = datetime.now()
        self.current_node = None
        self.progress = 0
        self.enable_db_logging = enable_db_logging
        self.user_id = user_id
        self.sequence_counter = 0

    async def _log_to_db(
        self,
        event_type: str,
        event_category: str,
        event_data: Dict[str, Any]
    ) -> None:
        """이벤트를 DB에 저장 (선택적)"""
        if not self.enable_db_logging:
            return

        try:
            self.sequence_counter += 1

            # workflow_events 테이블에 저장
            insert_query = """
                INSERT INTO workflow_events
                (session_id, user_id, event_type, event_category, sequence_number, event_data, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
            """

            await db_manager.execute(
                insert_query,
                self.session_id,
                self.user_id or "anonymous",
                event_type,
                event_category,
                self.sequence_counter,
                json.dumps(event_data)
            )

            logger.debug(
                f"[WorkflowEventLogger] Logged event #{self.sequence_counter}: {event_type}"
            )

        except Exception as e:
            logger.error(f"[WorkflowEventLogger] Failed to log to DB: {e}")
            # Non-critical error - continue without DB logging

    def _create_event(
        self,
        event_type: str,
        node_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        content: Optional[str] = None,
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        progress_percent: Optional[int] = None
    ) -> WorkflowStreamEvent:
        """스트리밍 이벤트 생성"""
        elapsed_ms = int((datetime.now() - self.start_time).total_seconds() * 1000)

        return WorkflowStreamEvent(
            event=event_type,
            session_id=self.session_id,
            timestamp=datetime.now().isoformat(),
            node_name=node_name or self.current_node,
            agent_name=agent_name,
            content=content,
            error=error,
            data=data or {},
            progress_percent=progress_percent or self.progress,
            execution_time_ms=elapsed_ms
        )

    # ============================================================================
    # WorkflowEventHandler 인터페이스 구현
    # ============================================================================

    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        """워크플로우 시작 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.STARTED,
            data={"query": workflow_input.get("query", "")[:100]}
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="workflow_started",
            event_category="workflow",
            event_data={
                "query": workflow_input.get("query", "")[:200],
                "user_id": workflow_input.get("user_id"),
                "session_id": workflow_input.get("session_id")
            }
        )

    async def on_node_start(
        self,
        node_name: str,
        step: int,
        total_steps: int,
        step_name: Optional[str] = None,
        estimated_remaining_s: Optional[float] = None,
    ):
        """노드 시작 이벤트 (structured progress 포함)"""
        self.current_node = node_name
        self.progress = int((step / total_steps) * 100)

        event = self._create_event(
            event_type=WorkflowStreamEventType.NODE_STARTED,
            node_name=node_name,
            data={
                "step": step,
                "total_steps": total_steps,
                "step_name": step_name or node_name.replace("_", " ").title(),
                "estimated_remaining_s": round(estimated_remaining_s, 1) if estimated_remaining_s is not None else None,
            },
            progress_percent=self.progress
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="node_started",
            event_category="workflow",
            event_data={
                "node_name": node_name,
                "step": step,
                "total_steps": total_steps,
                "step_name": step_name,
                "estimated_remaining_s": estimated_remaining_s,
                "progress_percent": self.progress
            }
        )

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        """노드 진행 상황 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.AGENT_PROGRESS,
            node_name=node_name,
            content=message,
            data={"sub_progress": progress}
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="node_progress",
            event_category="workflow",
            event_data={
                "node_name": node_name,
                "message": message,
                "sub_progress": progress
            }
        )

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        """노드 완료 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.NODE_COMPLETED,
            node_name=node_name,
            data=result
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="node_completed",
            event_category="workflow",
            event_data={
                "node_name": node_name,
                "result_summary": str(result)[:500]  # 결과 요약만 저장
            }
        )

    async def on_workflow_complete(self, result: Dict[str, Any]):
        """워크플로우 완료 이벤트"""
        self.progress = 100
        event = self._create_event(
            event_type=WorkflowStreamEventType.COMPLETED,
            data=result,
            progress_percent=100
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="workflow_completed",
            event_category="workflow",
            event_data={
                "response": str(result.get("response", ""))[:500],
                "quality_score": result.get("quality_score", 0.0),
                "execution_time_ms": result.get("execution_time_ms"),
                "cache_hit": result.get("cache_hit", False)
            }
        )

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        """워크플로우 에러 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.ERROR,
            node_name=node_name,
            error=str(error)
        )
        await self.event_queue.put(event)

        # DB 로깅
        await self._log_to_db(
            event_type="workflow_error",
            event_category="error",
            event_data={
                "node_name": node_name,
                "error_message": str(error),
                "error_type": type(error).__name__
            }
        )

    async def on_approval_request(self, pending_approvals: list, session_id: str) -> None:
        """interrupt_before=EXECUTION_APPROVAL 발동 시 클라이언트로 승인 요청 이벤트 발행."""
        event = self._create_event(
            event_type=WorkflowStreamEventType.APPROVAL_REQUEST,
            data={"pending_approvals": pending_approvals},
        )
        await self.event_queue.put(event)

    # ============================================================================
    # HDR (HyperDeep Research) Phase 이벤트 메서드들 — OpenResponses 브릿지
    # ============================================================================

    async def on_hdr_phase_start(self, phase_number: int, phase_name: str) -> None:
        """HDR Phase 시작 이벤트 — stream_adapter에서 FunctionCallItem(in_progress)로 변환됨."""
        safe_name = phase_name.lower().replace(" ", "_").replace("/", "_")
        event = self._create_event(
            event_type="hyper_deep_phase_start",
            node_name=f"hyper_deep:phase_{safe_name}",
            data={
                "phase_number": phase_number,
                "phase_name": phase_name,
            },
        )
        await self.event_queue.put(event)

    async def on_hdr_phase_complete(
        self,
        phase_number: int,
        phase_name: str,
        duration_ms: Optional[int] = None,
    ) -> None:
        """HDR Phase 완료 이벤트 — stream_adapter에서 FunctionCallItem(completed)로 변환됨."""
        safe_name = phase_name.lower().replace(" ", "_").replace("/", "_")
        event = self._create_event(
            event_type="hyper_deep_phase_complete",
            node_name=f"hyper_deep:phase_{safe_name}",
            data={
                "phase_number": phase_number,
                "phase_name": phase_name,
                "duration_ms": duration_ms,
            },
        )
        await self.event_queue.put(event)

    async def on_hdr_usage(self, estimated_tokens: int) -> None:
        """HDR 토큰 사용량 이벤트 — stream_adapter에서 ResponseObject.usage에 반영됨."""
        event = self._create_event(
            event_type="hyper_deep_usage",
            data={"estimated_total_tokens": estimated_tokens},
        )
        await self.event_queue.put(event)

    # ============================================================================
    # 기존 호환성 메서드들 (레거시 코드 지원)
    # ============================================================================

    async def on_agent_start(self, agent_name: str):
        """에이전트 시작 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.AGENT_STARTED,
            agent_name=agent_name
        )
        await self.event_queue.put(event)

    async def on_agent_progress(self, agent_name: str, message: str, sub_progress: int = 0):
        """에이전트 진행 상황 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.AGENT_PROGRESS,
            agent_name=agent_name,
            content=message,
            data={"sub_progress": sub_progress}
        )
        await self.event_queue.put(event)

    async def on_agent_complete(self, agent_name: str, result_count: int):
        """에이전트 완료 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.AGENT_COMPLETED,
            agent_name=agent_name,
            data={"result_count": result_count}
        )
        await self.event_queue.put(event)

    async def on_content_chunk(self, content: str):
        """컨텐츠 청크 이벤트 (부분 응답)"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.CONTENT_CHUNK,
            content=content
        )
        await self.event_queue.put(event)

    async def on_error(self, error_message: str, node_name: Optional[str] = None):
        """에러 이벤트"""
        event = self._create_event(
            event_type=WorkflowStreamEventType.ERROR,
            node_name=node_name,
            error=error_message
        )
        await self.event_queue.put(event)

    async def on_complete(self, result: Dict[str, Any]):
        """완료 이벤트"""
        self.progress = 100
        event = self._create_event(
            event_type=WorkflowStreamEventType.COMPLETED,
            data=result,
            progress_percent=100
        )
        await self.event_queue.put(event)


async def execute_workflow_with_streaming(
    user_id: str,
    session_id: str,
    query: str,
    callback: WorkflowStreamCallback,
    bypass_cache: bool = False
) -> Dict[str, Any]:
    """
    스트리밍 콜백과 함께 워크플로우 실행

    Dependency Injection 패턴을 사용하여 WorkflowEventHandler를 주입
    """

    try:
        # 워크플로우 입력 생성
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query
        }

        # Dependency Injection: WorkflowStreamCallback을 event_handler로 주입
        # 워크플로우 내부에서 발생하는 모든 이벤트가 자동으로 callback으로 전달됨
        result = await multi_agent_workflow.execute_workflow(
            workflow_input,
            event_handler=callback,  # DI: 이벤트 핸들러 주입
            bypass_cache=bypass_cache
        )

        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Workflow streaming error: {error_msg}")
        await callback.on_workflow_error(e)
        raise


# ============================================================================
# SSE Streaming Endpoint
# ============================================================================

@router.post("/query/stream")
async def stream_query(body: WorkflowStreamRequest, request: Request):
    """
    SSE 기반 워크플로우 스트리밍 엔드포인트 (Phase 3 개선)

    실시간으로 워크플로우 진행 상황과 결과를 스트리밍합니다.
    TTFB(Time To First Byte) 80% 단축 효과.

    Phase 3 개선사항:
    - Last-Event-ID 기반 재연결 지원
    - 이벤트 버퍼링 및 재전송
    - 연결 상태 관리

    이벤트 타입:
    - started: 워크플로우 시작
    - node_started: 노드 시작
    - node_completed: 노드 완료
    - agent_started: 에이전트 시작
    - agent_progress: 에이전트 진행 상황
    - agent_completed: 에이전트 완료
    - content_chunk: 부분 컨텐츠
    - progress_update: 진행률 업데이트
    - heartbeat: 연결 유지
    - error: 에러 발생
    - completed: 워크플로우 완료
    """

    session_id = body.session_id or str(uuid.uuid4())
    user_id = body.user_id or f"anonymous_{uuid.uuid4().hex[:8]}"
    stream_options = body.stream_options or {}

    # Last-Event-ID 헤더 확인 (재연결 지원)
    last_event_id = request.headers.get("Last-Event-ID")

    async def generate_stream() -> AsyncGenerator[str, None]:
        # StreamManager에서 세션 생성 (Phase 3)
        session = stream_manager.create_session(session_id, user_id)

        # 재연결 시 Last-Event-ID 이후 이벤트 재전송
        if last_event_id:
            logger.info(f"Reconnection detected for session {session_id}, last_event_id: {last_event_id}")
            missed_events = stream_manager.get_events_since(session_id, last_event_id)
            for event in missed_events:
                yield event.to_sse_format()
            logger.info(f"Resent {len(missed_events)} missed events")

        # 기존 콜백 생성
        event_queue: asyncio.Queue = asyncio.Queue()
        enable_db_logging = stream_options.get("enable_db_logging", True)
        callback = WorkflowStreamCallback(
            session_id=session_id,
            event_queue=event_queue,
            enable_db_logging=enable_db_logging,
            user_id=user_id
        )

        # 하트비트 태스크
        heartbeat_task = None
        if stream_options.get("include_heartbeat", True):
            heartbeat_interval = stream_options.get("heartbeat_interval_ms", 5000) / 1000

            async def send_heartbeat():
                while True:
                    await asyncio.sleep(heartbeat_interval)
                    heartbeat_event = callback._create_event(
                        event_type=WorkflowStreamEventType.HEARTBEAT
                    )
                    await event_queue.put(heartbeat_event)

            heartbeat_task = asyncio.create_task(send_heartbeat())

        # 워크플로우 실행 태스크
        workflow_task = asyncio.create_task(
            execute_workflow_with_streaming(
                user_id=user_id,
                session_id=session_id,
                query=request.query,
                callback=callback,
                bypass_cache=request.preferences.get("bypass_cache", False)
            )
        )

        try:
            completed = False
            while not completed:
                try:
                    # 이벤트 대기 (타임아웃 포함)
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    event_data = event.dict()
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                    if event.event in [WorkflowStreamEventType.COMPLETED, WorkflowStreamEventType.ERROR]:
                        completed = True

                except asyncio.TimeoutError:
                    # 타임아웃 시 워크플로우 완료 여부 확인
                    if workflow_task.done():
                        if workflow_task.exception():
                            error_event = callback._create_event(
                                event_type=WorkflowStreamEventType.ERROR,
                                error=str(workflow_task.exception())
                            )
                            yield f"data: {json.dumps(error_event.dict(), ensure_ascii=False)}\n\n"
                        completed = True

        except Exception as e:
            error_event = WorkflowStreamEvent(
                event=WorkflowStreamEventType.ERROR,
                session_id=session_id,
                error=str(e)
            )
            yield f"data: {json.dumps(error_event.dict(), ensure_ascii=False)}\n\n"

        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )


# ============================================================================
# WebSocket Streaming Endpoint
# ============================================================================

@router.websocket("/ws/query/{session_id}")
async def websocket_query_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket 기반 워크플로우 스트리밍 엔드포인트

    양방향 실시간 통신으로 워크플로우 진행 상황을 스트리밍합니다.

    클라이언트 메시지 형식:
    {
        "type": "query",
        "query": "사용자 질문",
        "user_id": "optional_user_id",
        "preferences": {"bypass_cache": false}
    }

    서버 응답 형식:
    {
        "event": "started|node_started|...|completed|error",
        "session_id": "...",
        "progress_percent": 0-100,
        "content": "...",
        "data": {...}
    }
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: session_id={session_id}")

    event_queue: asyncio.Queue = asyncio.Queue()
    # WebSocket에서도 DB 로깅 활성화 (기본값: True)
    callback = WorkflowStreamCallback(
        session_id=session_id,
        event_queue=event_queue,
        enable_db_logging=True,
        user_id=None  # 클라이언트 메시지에서 받아올 예정
    )
    active_task: Optional[asyncio.Task] = None

    try:
        # 연결 확인 메시지
        await websocket.send_json({
            "event": "connected",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "message": "워크플로우 스트리밍 준비 완료"
        })

        while True:
            # 클라이언트 메시지 수신
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            elif message_type == "query":
                query = data.get("query", "")
                user_id = data.get("user_id", f"ws_{uuid.uuid4().hex[:8]}")
                preferences = data.get("preferences", {})

                if not query:
                    await websocket.send_json({
                        "event": "error",
                        "error": "쿼리가 비어있습니다"
                    })
                    continue

                # 이전 태스크 취소
                if active_task and not active_task.done():
                    active_task.cancel()

                # 새 콜백 생성 (user_id 업데이트)
                event_queue = asyncio.Queue()
                callback = WorkflowStreamCallback(
                    session_id=session_id,
                    event_queue=event_queue,
                    enable_db_logging=True,
                    user_id=user_id
                )

                # 워크플로우 실행
                async def run_workflow():
                    try:
                        await execute_workflow_with_streaming(
                            user_id=user_id,
                            session_id=session_id,
                            query=query,
                            callback=callback,
                            bypass_cache=preferences.get("bypass_cache", False)
                        )
                    except Exception as e:
                        await callback.on_error(str(e))

                active_task = asyncio.create_task(run_workflow())

                # 이벤트 스트리밍
                async def stream_events():
                    while True:
                        try:
                            event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                            await websocket.send_json(event.dict())

                            if event.event in [WorkflowStreamEventType.COMPLETED, WorkflowStreamEventType.ERROR]:
                                break

                        except asyncio.TimeoutError:
                            if active_task.done():
                                break
                        except Exception:
                            break

                await stream_events()

            elif message_type == "cancel":
                if active_task and not active_task.done():
                    active_task.cancel()
                    await websocket.send_json({
                        "event": "cancelled",
                        "session_id": session_id,
                        "message": "워크플로우가 취소되었습니다"
                    })

            else:
                await websocket.send_json({
                    "event": "error",
                    "error": f"알 수 없는 메시지 타입: {message_type}"
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session_id={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "event": "error",
                "error": str(e)
            })
        except:
            pass
    finally:
        if active_task and not active_task.done():
            active_task.cancel()
        try:
            await websocket.close()
        except:
            pass


# ============================================================================
# Enhanced WebSocket with Multi-Agent Progress
# ============================================================================

@router.websocket("/ws/query/detailed/{session_id}")
async def websocket_detailed_query_stream(websocket: WebSocket, session_id: str):
    """
    상세 진행 상황을 포함한 WebSocket 스트리밍

    에이전트별 세부 진행 상황과 중간 결과를 실시간으로 제공합니다.
    """
    await websocket.accept()
    logger.info(f"Detailed WebSocket connected: session_id={session_id}")

    try:
        await websocket.send_json({
            "event": "connected",
            "session_id": session_id,
            "features": ["detailed_progress", "agent_status", "partial_results"],
            "timeout_config": {
                "search": settings.SEARCH_ORCHESTRATION_TIMEOUT,
                "default_agent": settings.AGENT_TIMEOUT,
                "agent_timeouts": settings.AGENT_TIMEOUTS
            }
        })

        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif message_type == "query":
                query = data.get("query", "")
                user_id = data.get("user_id", f"ws_{uuid.uuid4().hex[:8]}")

                if not query:
                    await websocket.send_json({"event": "error", "error": "Empty query"})
                    continue

                # 사용자 생성/조회
                await QueryService.get_or_create_user(user_id)

                # 시작 알림
                await websocket.send_json({
                    "event": "started",
                    "session_id": session_id,
                    "query": query[:100],
                    "timestamp": datetime.now().isoformat()
                })

                # 워크플로우 노드 목록
                nodes = [
                    ("query_classifier", "쿼리 분석", 10),
                    ("skill_tool_selector", "도구 선택", 15),
                    ("search_orchestrator", "검색 수행", 40),
                    ("analysis_orchestrator", "분석 수행", 20),
                    ("generation_orchestrator", "생성 수행", 5),
                    ("result_integrator", "결과 통합", 5),
                    ("quality_validator", "품질 검증", 3),
                    ("response_generator", "응답 생성", 2)
                ]

                cumulative_progress = 0

                try:
                    for node_name, description, weight in nodes:
                        # 노드 시작
                        await websocket.send_json({
                            "event": "node_started",
                            "node_name": node_name,
                            "description": description,
                            "progress_percent": cumulative_progress
                        })

                        # 진행 시뮬레이션 (실제로는 콜백 기반으로 대체)
                        await asyncio.sleep(0.05)

                        cumulative_progress += weight

                        # 노드 완료
                        await websocket.send_json({
                            "event": "node_completed",
                            "node_name": node_name,
                            "progress_percent": cumulative_progress
                        })

                    # 실제 워크플로우 실행
                    result = await QueryService.process_query_workflow(
                        user_id=user_id,
                        session_id=session_id,
                        query=query,
                        bypass_cache=data.get("preferences", {}).get("bypass_cache", False)
                    )

                    # 완료
                    await websocket.send_json({
                        "event": "completed",
                        "session_id": session_id,
                        "progress_percent": 100,
                        "response": result.get("response"),
                        "quality_score": result.get("quality_score", 0.0),
                        "execution_time_ms": result.get("execution_time_ms"),
                        "cache_hit": result.get("cache_hit", False)
                    })

                except Exception as e:
                    logger.error(f"Workflow error: {e}")
                    await websocket.send_json({
                        "event": "error",
                        "error": str(e)
                    })

            elif message_type == "get_status":
                await websocket.send_json({
                    "event": "status",
                    "session_id": session_id,
                    "agent_timeouts": settings.AGENT_TIMEOUTS,
                    "search_timeout": settings.SEARCH_ORCHESTRATION_TIMEOUT
                })

    except WebSocketDisconnect:
        logger.info(f"Detailed WebSocket disconnected: session_id={session_id}")
    except Exception as e:
        logger.error(f"Detailed WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass
