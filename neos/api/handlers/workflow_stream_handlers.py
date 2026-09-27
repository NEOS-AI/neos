"""
Workflow Streaming 콜백 - 워크플로우 이벤트를 스트림 큐로 옮긴다

이 모듈에는 `POST /query/stream` 과 `/ws/query/*` 라우트가 있었다(2026-09-27
제거, `tests/api/test_retired_routes.py`). 남은 것은 챗 SSE 파이프라인과 A2UI 가
쓰는 `WorkflowStreamCallback` 이다.

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
"""

from typing import Dict, Any, Optional
from datetime import datetime
import json
import asyncio

from neos.api.models.query_models import (
    WorkflowStreamEvent,
    WorkflowStreamEventType
)
from neos.workflow.events import WorkflowEventHandler
from neos.utils.logger import get_logger
from neos.database.connection import db_manager

logger = get_logger(__name__)


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

    async def on_ui_frame(self, ui_frame: dict) -> None:
        """Phase 8 (A2UI): UIFrameGenerator 노드에서 UIFrame 생성 시 SSE 이벤트 발행.

        클라이언트는 "ui_frame" 이벤트 수신 시 UIFrameRenderer로 폼을 렌더링하고,
        사용자 제출 후 POST /api/v1/ui/submit을 호출해야 한다.
        """
        event = self._create_event(
            event_type=WorkflowStreamEventType.UI_FRAME,
            data={"ui_frame": ui_frame},
        )
        await self.event_queue.put(event)

    async def on_deep_analysis_started(
        self,
        run_id: str,
        events_url: str,
        assistant_message_id: Optional[str] = None,
    ) -> None:
        """Phase 3b(D23): deep analysis job 제출 핸들을 클라이언트로 발행한다.

        챗 턴은 이 이벤트 뒤 즉시 종료한다. 진행 상황은 events_url의 전용
        SSE 스트림이 전달한다 -- 챗과 전용 API가 같은 계약을 쓴다.
        """
        event = self._create_event(
            event_type=WorkflowStreamEventType.DEEP_ANALYSIS_STARTED,
            data={
                "run_id": run_id,
                "events_url": events_url,
                "assistant_message_id": assistant_message_id,
            },
        )
        await self.event_queue.put(event)

    def on_graph_subagent_event(self, kind: str, payload: Dict[str, Any]) -> None:
        """설계 그래프 서브에이전트 노드의 걸음·폴드를 스트림에 싣는다.

        **동기**다 -- 서브에이전트 호스트의 `emit` 이 동기라서다
        (`neos.workflow.events.forward_graph_subagent_event`). 큐가 차면 버린다:
        진행 표시 때문에 그래프가 멈추면 안 된다. 본문 필터는 SSE 변환
        (`stream_adapter.graph_subagent_event_from`)이 한다.
        """
        event = self._create_event(
            event_type=WorkflowStreamEventType.GRAPH_SUBAGENT,
            node_name=payload.get("node"),
            data={"kind": kind, **payload},
        )
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("graph subagent event dropped (queue full) kind=%s", kind)

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
