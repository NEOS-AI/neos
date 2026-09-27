"""Authenticated job API for loop-based deep analysis runs.

Phase 3a(D22): 제출과 실행을 분리한다. `POST`는 run을 만들고 job을
디스패치한 뒤 **즉시 202를 반환**한다(AC1). 진행 상황은
`GET /{run_id}/events`가 append-only 이벤트 로그를 seq 커서로 재생해
전달한다 -- 이 매체가 DB이므로 Celery 워커가 넣은 이벤트를 API 프로세스가
볼 수 있다(`stream_manager`는 프로세스 내 dict라 불가능하다).

동기 요청 안에서 심층분석을 완주시키려는 시도 자체가 구조적으로 틀렸다:
프론트 maxDuration 60s < 노드 캡 300s < dig 하나의 wall_clock_cap 600s.
가장 작은 예산이 클라이언트 쪽에 있으므로, 라운드를 여러 번 도는 run은
어떤 동기 요청 예산에도 맞지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from neos.api.dependencies.auth import get_current_active_user
from neos.api.models.deep_analysis_models import (
    DeepAnalysisJobResponse,
    DeepAnalysisRequest,
)
from neos.api.services.chat_service import ChatService
from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.database.models import User
from neos.tasks.deep_analysis_job_task import (
    DeepAnalysisDispatchError,
    submit_deep_analysis_job,
)
from neos.utils.logger import get_logger
from neos.workflow.deep_analysis.event_stream import (
    get_run_owner,
    read_events_after,
)
from neos.workflow.deep_analysis.jobs import (
    RESUMABLE_STATUSES,
    TERMINAL_JOB_KINDS,
)
from neos.workflow.deep_analysis.ledger import create_run


logger = get_logger(__name__)
router = APIRouter()


def _events_url(run_id: str) -> str:
    return f"{settings.API_V1_PREFIX}/deep-analysis/{run_id}/events"


async def _submit_or_503(*args, **kwargs) -> str:
    try:
        return await submit_deep_analysis_job(*args, **kwargs)
    except DeepAnalysisDispatchError as exc:
        raise HTTPException(
            status_code=503,
            detail="Deep analysis dispatch unavailable",
        ) from exc


async def ensure_owned_conversation(
    conversation_id: str | None,
    user_id: str,
    chat_service=ChatService,
):
    if conversation_id is None:
        return None
    conversation = await chat_service.get_conversation(conversation_id)
    if conversation is None or conversation.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return conversation


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _require_owned_run(run_id: str, user_id: str) -> tuple[str | None, str]:
    async with await db_manager.get_session() as session:
        owner = await get_run_owner(session, run_id)
    if owner is None or owner[0] != user_id:
        # 존재 여부를 흘리지 않는다.
        raise HTTPException(status_code=404, detail="Resource not found")
    return owner


@router.post(
    "/deep-analysis",
    status_code=202,
    response_model=DeepAnalysisJobResponse,
)
async def start_deep_analysis(
    request: DeepAnalysisRequest,
    current_user: User = Depends(get_current_active_user),
) -> DeepAnalysisJobResponse:
    """run을 생성하고 job을 디스패치한 뒤 즉시 반환한다(AC1)."""
    conversation = await ensure_owned_conversation(
        request.conversation_id,
        current_user.user_id,
    )
    assistant_message_id = str(uuid.uuid4()) if conversation is not None else None

    if conversation is not None:
        await ChatService.add_message(
            conversation_id=request.conversation_id,
            role="user",
            content=request.question,
            metadata={"deep_analysis_initiated": True},
        )

    async with await db_manager.get_session() as session:
        run_id = await create_run(
            session,
            request.question,
            request.profile,
            user_id=current_user.user_id,
            conversation_id=request.conversation_id,
            assistant_message_id=assistant_message_id,
        )
        # 커밋이 필수다 -- job이 다른 프로세스/태스크에서 이 run을 읽는다.
        await session.commit()

    executor = await _submit_or_503(
        run_id,
        request.question,
        request.profile,
    )
    logger.info(
        "deep_analysis run %s submitted by %s via %s",
        run_id,
        current_user.user_id,
        executor,
    )
    return DeepAnalysisJobResponse(
        run_id=run_id,
        status="accepted",
        executor=executor,
        events_url=_events_url(run_id),
    )


@router.get("/deep-analysis/{run_id}/events")
async def stream_deep_analysis_events(
    run_id: str,
    request: Request,
    after: int = Query(
        0, ge=0, description="이 seq보다 큰 이벤트만. 0이면 전체 이력."
    ),
    current_user: User = Depends(get_current_active_user),
):
    """이벤트 로그를 seq 커서로 재생 + 라이브 tail (AC6).

    `after=0`(기본)이면 진행 중인 run이라도 처음부터 전부 받는다. 재접속
    클라이언트는 마지막으로 받은 seq를 넘겨 이어받는다.
    """
    await _require_owned_run(run_id, current_user.user_id)
    config = settings.config.deep_analysis

    async def generate():
        cursor = after
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return

            async with await db_manager.get_session() as session:
                events = await read_events_after(session, run_id, cursor)

            if events:
                idle = 0.0
                for event in events:
                    cursor = event["seq"]
                    yield _sse(event)
                # 끝은 **마지막** 종결 이벤트다. 재개된 run 의 이력에는 옛
                # `job_failed` 뒤에 `job_resumed` 가 오므로, 첫 종결에서 닫으면
                # 재생하는 사람은 살아 있는 run 을 실패로 본다. 종결이 배치 끝에
                # 걸렸다면 뒤에 더 있는지 한 번 더 읽어 보고 없을 때만 닫는다.
                if events[-1]["type"] in TERMINAL_JOB_KINDS:
                    async with await db_manager.get_session() as session:
                        later = await read_events_after(session, run_id, cursor)
                    if not later:
                        return
                # 배치가 꽉 찼을 수 있으므로 곧바로 다음 배치를 읽는다.
                continue

            yield ": keepalive\n\n"
            await asyncio.sleep(config.events_poll_interval)
            idle += config.events_poll_interval
            if idle >= config.events_stream_idle_timeout:
                yield _sse(
                    {
                        "type": "stream_idle_timeout",
                        "run_id": run_id,
                        "seq": cursor,
                    }
                )
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/deep-analysis/{run_id}/resume",
    status_code=202,
    response_model=DeepAnalysisJobResponse,
)
async def resume_deep_analysis(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
) -> DeepAnalysisJobResponse:
    """중단된 run을 재개한다(AC5).

    중복 지출은 원장이 막는다 -- 소비된 토큰은 `DAQuestion.spent_tokens`에,
    충돌 재조사 소진은 이벤트 로그에 남아 있다. 재개는 새 상태 저장소가
    아니라 진입점이다(스펙 §5.3).
    """
    _owner_id, status = await _require_owned_run(run_id, current_user.user_id)
    if status not in RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"run is {status!r} and cannot be resumed",
        )

    executor = await _submit_or_503(run_id, resume=True)
    logger.info(
        "deep_analysis run %s resumed by %s via %s",
        run_id,
        current_user.user_id,
        executor,
    )
    return DeepAnalysisJobResponse(
        run_id=run_id,
        status="accepted",
        executor=executor,
        events_url=_events_url(run_id),
    )
