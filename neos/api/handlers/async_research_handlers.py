"""
Async Research API Handlers (Phase 3.5)

Celery를 통한 비동기 연구 실행 및 SSE 진행 상황 스트리밍.
deep_research, hyper_deep_research 등 무거운 쿼리를 비동기로 처리합니다.
"""

import json
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_active_user
from neos.api.dependencies.resource_access import get_owned_conversation
from neos.database.models import User
from neos.config.settings import settings
from neos.utils.cache import cache_manager
from neos.workflow.stream_manager import stream_manager

router = APIRouter(prefix="/api/v1/research", tags=["async-research"])
logger = logging.getLogger(__name__)

JOB_OWNER_TTL_SECONDS = 86400


def _job_owner_cache_key(job_id: str) -> str:
    return cache_manager.make_key("async_research_job_owner", job_id)


def _session_owner_cache_key(session_id: str) -> str:
    return cache_manager.make_key("async_research_session_owner", session_id)


# ============================================================================
# Request/Response Models
# ============================================================================

class AsyncResearchRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    language: str = "auto"


class AsyncResearchResponse(BaseModel):
    job_id: str
    session_id: str
    status: str
    stream_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED
    result: Optional[dict] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/async", response_model=AsyncResearchResponse)
async def start_async_research(
    request: AsyncResearchRequest,
    current_user: User = Depends(get_current_active_user),
):
    """비동기 연구 시작 — 즉시 job_id 반환, SSE로 진행 상황 스트리밍

    deep_research, hyper_deep_research intent에 적합합니다.
    경량 쿼리는 기존 /api/v1/chat 엔드포인트를 사용하세요.
    """
    if not getattr(settings, "CELERY_ENABLED", False):
        raise HTTPException(
            status_code=503,
            detail="Async research is not available (CELERY_ENABLED=false)",
        )

    session_id = str(uuid.uuid4())
    if request.conversation_id:
        await get_owned_conversation(request.conversation_id, current_user)

    try:
        session_owner_recorded = await cache_manager.set(
            _session_owner_cache_key(session_id),
            current_user.user_id,
            ttl=JOB_OWNER_TTL_SECONDS,
        )
        if not session_owner_recorded:
            raise RuntimeError("Failed to record async research session owner")

        from neos.workflow.celery_tasks import execute_workflow_async

        task = execute_workflow_async.apply_async(
            kwargs={
                "query": request.query,
                "user_id": current_user.user_id,
                "conversation_id": request.conversation_id or session_id,
                "session_id": session_id,
                "language": request.language,
            },
            queue="search",
        )
        owner_recorded = await cache_manager.set(
            _job_owner_cache_key(task.id),
            current_user.user_id,
            ttl=JOB_OWNER_TTL_SECONDS,
        )
        if not owner_recorded:
            raise RuntimeError("Failed to record async research job owner")

        logger.info(
            f"Async research submitted: job_id={task.id}, "
            f"session={session_id}, user={current_user.user_id}"
        )

        return AsyncResearchResponse(
            job_id=task.id,
            session_id=session_id,
            status="submitted",
            stream_url=f"/api/v1/research/stream/{session_id}",
        )

    except Exception as e:
        logger.error(f"Failed to submit async research: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit research task")


@router.get("/async/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """비동기 연구 작업 상태 조회"""
    if not getattr(settings, "CELERY_ENABLED", False):
        raise HTTPException(status_code=503, detail="Celery not enabled")

    owner_id = await cache_manager.get(_job_owner_cache_key(job_id))
    if owner_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Resource not found")

    try:
        from neos.workflow.celery_app import app as celery_app

        result = celery_app.AsyncResult(job_id)

        response = JobStatusResponse(
            job_id=job_id,
            status=result.status,
        )

        if result.ready():
            response.result = result.result if isinstance(result.result, dict) else {"value": str(result.result)}

        return response

    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get job status")


@router.get("/stream/{session_id}")
async def stream_research_progress(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_active_user),
):
    """SSE 스트리밍으로 연구 진행 상황 수신

    워크플로우 노드 실행 이벤트를 실시간으로 스트리밍합니다.
    workflow_completed 또는 workflow_failed 이벤트 수신 시 스트림이 종료됩니다.
    """
    owner_id = await cache_manager.get(_session_owner_cache_key(session_id))
    if owner_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Resource not found")

    try:
        stream_manager.claim_session(session_id, current_user.user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Resource not found")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                events = stream_manager.get_events_since(session_id)

                for event in events:
                    data = json.dumps(event.data) if isinstance(event.data, dict) else str(event.data)
                    yield f"id: {event.id}\nevent: {event.event}\ndata: {data}\n\n"

                    # 워크플로우 완료/실패 시 스트림 종료
                    if event.event in ("workflow_completed", "workflow_failed"):
                        return

                # Heartbeat
                yield ": heartbeat\n\n"

                # 짧은 대기 후 새 이벤트 확인
                import asyncio
                await asyncio.sleep(1.0)

        finally:
            stream_manager.disconnect(session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
