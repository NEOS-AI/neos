"""Execution Approval API Handlers (Phase 2 — OpenClaw Exec Approval System)

LangGraph Human-in-the-Loop 패턴의 resume 엔드포인트를 제공한다.

흐름:
    1. 워크플로우가 EXECUTION_APPROVAL interrupt_before에 의해 중단됨
    2. SSE 스트림으로 approval_request 이벤트 발행
    3. 클라이언트가 POST /api/v1/approval/respond 호출
    4. graph.aupdate_state → approval_decision 설정
    5. graph.astream(None) 로 워크플로우 resume (백그라운드 태스크)
       → stream_manager.add_event()로 결과 push
    6. 클라이언트가 GET /api/v1/approval/stream/{session_id}로 재구독하여 최종 응답 수신
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.workflow.graph import multi_agent_workflow
from neos.workflow.stream_manager import stream_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approval", tags=["Execution Approval"])


class ApprovalResponse(BaseModel):
    """POST /approval/respond 요청 본문"""
    session_id: str = Field(..., description="워크플로우 세션 ID (thread_id)")
    request_id: str = Field(..., description="approval_request 이벤트의 request_id")
    decision: Literal["approved", "rejected"] = Field(..., description="사용자 결정")
    add_to_allowlist: bool = Field(
        default=False,
        description="True이면 해당 스킬을 allowlist에 추가하여 이후 자동 승인",
    )
    skill_name: Optional[str] = Field(
        default=None,
        description="allowlist에 추가할 스킬 이름 (add_to_allowlist=True 시 필요)",
    )


class ApprovalResponseResult(BaseModel):
    """POST /approval/respond 응답"""
    status: str
    session_id: str
    decision: str


@router.post(
    "/respond",
    response_model=ApprovalResponseResult,
    summary="실행 승인 결정 제출",
    description=(
        "중단된 워크플로우에 승인/거부 결정을 전달하고 재개한다. "
        "클라이언트는 approval_request SSE 이벤트를 받은 후 이 엔드포인트를 호출해야 한다. "
        "응답 후 GET /api/v1/approval/stream/{session_id}로 재구독하여 결과를 받는다."
    ),
)
async def respond_to_approval(
    body: ApprovalResponse,
    current_user: User = Depends(get_current_user),
) -> ApprovalResponseResult:
    """
    중단된 워크플로우에 승인 결정을 전달하고 재개한다.

    1. 현재 pending_approvals에서 request_id 유효성 검증 (H3)
    2. graph.aupdate_state: approval_decision을 상태에 업데이트
    3. asyncio.create_task: 백그라운드에서 그래프 재개 + stream_manager로 결과 push (C5, H4)
    4. add_to_allowlist=True이면 DB에 allowlist 등록
    """
    session_id = body.session_id
    decision = body.decision

    # 그래프가 초기화되어 있어야 함
    if not multi_agent_workflow._graph_initialized or not multi_agent_workflow._graph_uses_checkpointer:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="워크플로우가 checkpointer 모드로 초기화되지 않았습니다.",
        )

    graph = multi_agent_workflow.graph
    config = {"configurable": {"thread_id": session_id}}

    # [H3] aupdate_state 이전: 현재 pending_approvals에서 request_id 유효성 검증
    try:
        current_graph_state = await graph.aget_state(config)
        pending = current_graph_state.values.get("pending_approvals") or []
    except Exception as e:
        logger.error(f"[ApprovalHandler] aget_state failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 상태 조회 실패: {str(e)}",
        )

    valid_ids = {p["request_id"] for p in pending}
    if body.request_id not in valid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 request_id입니다. 해당 세션의 pending approval이 아닙니다.",
        )

    # allowlist 추가 시 skill_name이 request_id의 스킬과 일치하는지 검증
    if body.add_to_allowlist and body.skill_name:
        matching = next((p for p in pending if p["request_id"] == body.request_id), None)
        if not matching or matching.get("skill_name") != body.skill_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="skill_name이 해당 request_id의 스킬과 일치하지 않습니다.",
            )

    try:
        # 1. 상태 업데이트: approval_decision 설정
        await graph.aupdate_state(
            config=config,
            values={"approval_decision": decision},
        )
        logger.info(
            f"[ApprovalHandler] approval_decision={decision!r} set for session={session_id}"
        )
    except Exception as e:
        logger.error(f"[ApprovalHandler] aupdate_state failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"상태 업데이트 실패: {str(e)}",
        )

    # [C5, H4] 백그라운드 태스크로 그래프 재개 — stream_manager로 결과 push
    # 클라이언트는 GET /api/v1/approval/stream/{session_id}로 재구독하여 결과를 받는다.
    async def _resume():
        # stream_manager 세션 확보 (이미 있으면 재사용)
        if not stream_manager.get_session(session_id):
            stream_manager.create_session(session_id, current_user.user_id)
        try:
            final_state = None
            async for chunk in graph.astream(None, config=config):
                for node_name, state in chunk.items():
                    await stream_manager.add_event(
                        session_id, "node_complete", {"node": node_name}
                    )
                    final_state = state

            final_response = (
                final_state.get("final_response", "") if final_state else ""
            )
            await stream_manager.add_event(
                session_id, "completed", {"response": final_response}
            )
            logger.info(f"[ApprovalHandler] Workflow resumed and completed: session={session_id}")

        except Exception as e:
            logger.error(
                f"[ApprovalHandler] Workflow resume failed: session={session_id}: {e}"
            )
            # [H4] 예외 발생 시 에러 이벤트 push — 클라이언트가 무한 대기 방지
            await stream_manager.add_event(
                session_id, "error", {"message": str(e)}
            )

    asyncio.create_task(_resume(), name=f"approval_resume_{session_id}")

    # allowlist 등록 (선택적, H3에서 이미 검증 완료)
    if body.add_to_allowlist and body.skill_name:
        await _add_to_allowlist(
            user_id=current_user.user_id,
            skill_name=body.skill_name,
        )

    return ApprovalResponseResult(
        status="resumed",
        session_id=session_id,
        decision=decision,
    )


@router.get(
    "/stream/{session_id}",
    summary="Approval resume 후 워크플로우 결과 스트리밍",
    description=(
        "POST /approval/respond 호출 후 클라이언트가 재구독할 SSE 엔드포인트. "
        "백그라운드에서 재개된 워크플로우의 진행 상황과 최종 응답을 수신한다."
    ),
)
async def stream_resume_result(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    approval resume 후 워크플로우 결과를 SSE로 스트리밍한다.

    _resume() 백그라운드 태스크가 stream_manager.add_event()로 push한 이벤트를
    세션 큐에서 읽어 클라이언트로 전달한다. 60초 타임아웃 후 자동 종료.
    """
    async def generate() -> AsyncGenerator[str, None]:
        session = stream_manager.get_session(session_id)
        if not session:
            yield f"data: {json.dumps({'event': 'error', 'message': '세션을 찾을 수 없습니다.'})}\n\n"
            return

        try:
            while True:
                event = await asyncio.wait_for(session.queue.get(), timeout=60.0)
                yield event.to_sse_format()
                if event.event in ("completed", "error"):
                    break
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'event': 'error', 'message': '워크플로우 응답 대기 타임아웃'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _add_to_allowlist(user_id: str, skill_name: str) -> None:
    """사용자의 스킬을 allowlist에 추가한다 (이미 있으면 업데이트)."""
    try:
        from neos.database.connection import db_manager
        sql = """
            INSERT INTO tool_approval_allowlist (user_id, skill_name, auto_approved, created_at)
            VALUES ($1, $2, TRUE, NOW())
            ON CONFLICT (user_id, skill_name) DO UPDATE
                SET auto_approved = TRUE
        """
        await db_manager.execute(sql, user_id, skill_name)
        logger.info(f"[ApprovalHandler] Allowlist updated: user={user_id}, skill={skill_name}")
    except Exception as e:
        logger.warning(f"[ApprovalHandler] Allowlist update failed (non-critical): {e}")
