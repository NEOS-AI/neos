"""UI Frame Submit Handlers (Phase 8 — OpenClaw A2UI)

UI 폼 제출 엔드포인트를 제공한다.

⚠️ 중요: UI_FRAME_GENERATOR → END로 완료된 그래프는 resume 불가.
   새 워크플로우 invoke 방식을 사용한다.

흐름:
    1. UIFrameGenerator가 UIFrame 생성 → SSE "ui_frame" 이벤트 발행
    2. 클라이언트: 폼 작성 후 POST /api/v1/ui/submit 호출
    3. frame_id로 UIFrameSession DB 조회 → 원본 쿼리 복원
    4. needs_ui=False + ui_submission 포함한 새 state로 워크플로우 invoke
    5. 기존 SSE 채널로 결과 스트리밍 (conversation_id 동일)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update as sa_update

from neos.api.dependencies.auth import get_current_user
from neos.api.models.ui_components import UISubmitRequest
from neos.database.connection import get_db_session
from neos.database.models import UIFrameSession, User
from neos.workflow.graph import multi_agent_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["A2UI"])


async def _get_owned_frame_session(
    frame_id: uuid.UUID,
    user_id: str,
) -> UIFrameSession | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(UIFrameSession).where(
                UIFrameSession.frame_id == frame_id,
                UIFrameSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


@router.post(
    "/submit",
    summary="UI 폼 제출",
    description=(
        "UIFrameGenerator가 생성한 폼의 사용자 입력값을 제출하여 워크플로우를 재실행한다. "
        "UI_FRAME_GENERATOR → END로 완료된 그래프는 resume 불가이므로 새 invoke 방식을 사용."
    ),
)
async def submit_ui_frame(
    body: UISubmitRequest,
    current_user: User = Depends(get_current_user),
):
    """
    1. frame_id로 UIFrameSession 조회
    2. 만료 여부 확인
    3. needs_ui=False + ui_submission 포함 새 워크플로우 invoke
    """
    frame_uuid = uuid.UUID(body.frame_id)
    frame_session = await _get_owned_frame_session(
        frame_uuid,
        current_user.user_id,
    )

    if not frame_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    if frame_session.session_id != body.session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    # 만료 확인
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if frame_session.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="UIFrame이 만료되었습니다. 다시 요청해주세요.",
        )

    # 중복 제출 방어 — submitted_at을 원자적으로 설정 (미제출 레코드만 업데이트)
    async with get_db_session() as db:
        update_result = await db.execute(
            sa_update(UIFrameSession)
            .where(
                UIFrameSession.frame_id == frame_uuid,
                UIFrameSession.user_id == current_user.user_id,
                UIFrameSession.submitted_at.is_(None),  # 아직 제출되지 않은 경우만
            )
            .values(submitted_at=now)
            .returning(UIFrameSession.frame_id)
        )
        await db.commit()

    if update_result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 제출된 UIFrame입니다.",
        )

    # 새 워크플로우 invoke
    # needs_ui=False: 폼 완료 → 실행 처리 경로로 라우팅 (UI_FRAME_GENERATOR 재진입 방지)
    workflow_input = {
        "user_id": str(current_user.user_id),
        "session_id": body.session_id,
        "query": frame_session.original_query,
        "ui_submission": body.values,
        "needs_ui": False,
    }
    if frame_session.conversation_id:
        workflow_input["conversation_id"] = str(frame_session.conversation_id)

    logger.info(
        "[UISubmit] frame_id=%s, query=%s..., values_keys=%s",
        body.frame_id,
        frame_session.original_query[:40],
        list(body.values.keys()),
    )

    # 워크플로우 결과를 SSE 스트림으로 방출 (chat_handlers.py 패턴 재사용)
    return StreamingResponse(
        _event_generator(workflow_input, body.session_id, str(current_user.user_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(workflow_input: dict, session_id: str, user_id: str):
    """워크플로우 실행 결과를 SSE 스트림으로 방출한다."""
    from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback
    from neos.api.models.query_models import WorkflowStreamEventType

    event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    callback = WorkflowStreamCallback(
        session_id=session_id,
        event_queue=event_queue,
        enable_db_logging=False,
        user_id=user_id,
    )
    workflow_task = asyncio.create_task(
        multi_agent_workflow.execute_workflow(
            workflow_input,
            event_handler=callback,
            use_checkpointer=False,
        )
    )
    try:
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                yield f"data: {event.model_dump_json()}\n\n"
            except asyncio.TimeoutError:
                if workflow_task.done():
                    if workflow_task.exception():
                        err = str(workflow_task.exception())
                        logger.error("[UISubmit] Workflow failed: %s", err)
                        error_event = callback._create_event(
                            event_type=WorkflowStreamEventType.ERROR,
                            error=err,
                        )
                        yield f"data: {error_event.model_dump_json()}\n\n"
                    break
            except Exception as exc:
                logger.error("[UISubmit] SSE stream error: %s", exc)
                break
    finally:
        if not workflow_task.done():
            workflow_task.cancel()
    yield "data: [DONE]\n\n"
