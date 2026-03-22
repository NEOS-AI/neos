"""Scheduled Tasks API Handlers

Phase 4 (OpenClaw Cron 스케줄 스킬)

엔드포인트:
    POST   /api/v1/scheduled-tasks          스케줄 등록
    GET    /api/v1/scheduled-tasks          내 스케줄 목록
    GET    /api/v1/scheduled-tasks/{id}     스케줄 상세
    PATCH  /api/v1/scheduled-tasks/{id}     수정 (활성화/비활성화)
    DELETE /api/v1/scheduled-tasks/{id}     삭제
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from neos.api.dependencies.auth import get_current_user
from neos.database.connection import get_async_session
from neos.database.models import ScheduledTask, User
from neos.skills.builtin.cron.parser import parse_schedule, validate_cron_expression

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduled-tasks", tags=["Scheduled Tasks"])


# ============================================================================
# Pydantic 스키마
# ============================================================================

class ScheduledTaskCreate(BaseModel):
    """스케줄 등록 요청"""
    query: str = Field(..., min_length=1, max_length=2000, description="원본 쿼리")
    cron_expression: Optional[str] = Field(
        None, description="직접 cron 표현식 지정 시 파서 건너뜀"
    )
    timezone: str = Field("UTC", description="타임존 (예: Asia/Seoul)")
    channel_type: str = Field("api", description="결과 전송 채널 (api | telegram | discord)")
    channel_id: Optional[str] = Field(None, description="외부 채널 ID")


class ScheduledTaskUpdate(BaseModel):
    """스케줄 수정 요청"""
    is_active: Optional[bool] = Field(None, description="활성화 여부")
    cron_expression: Optional[str] = Field(None, description="cron 표현식 변경")


class ScheduledTaskResponse(BaseModel):
    """스케줄 응답"""
    id: str
    title: str
    query: str
    cron_expression: str
    timezone: str
    channel_type: str
    channel_id: Optional[str]
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: datetime
    run_count: int
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================================
# 엔드포인트
# ============================================================================

@router.post(
    "",
    response_model=ScheduledTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="스케줄 등록",
)
async def create_scheduled_task(
    payload: ScheduledTaskCreate,
    current_user: User = Depends(get_current_user),
):
    """사용자 자연어 쿼리를 cron 스케줄로 등록한다.

    cron_expression을 직접 전달하지 않으면 자연어 파서로 변환을 시도한다.
    """
    from croniter import croniter

    # cron 표현식 결정
    if payload.cron_expression:
        if not validate_cron_expression(payload.cron_expression):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"유효하지 않은 cron 표현식: {payload.cron_expression}",
            )
        cron_expr = payload.cron_expression
        description = f"커스텀 스케줄: {cron_expr}"
    else:
        parsed = parse_schedule(payload.query, default_timezone=payload.timezone)
        if not parsed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "쿼리에서 스케줄 시간을 파싱하지 못했습니다. "
                    "'매일 오전 9시 ...', '매주 월요일 ...' 형식으로 입력하거나 "
                    "cron_expression을 직접 전달하세요."
                ),
            )
        cron_expr = parsed.cron_expression
        description = parsed.description

    # 다음 실행 시각 계산
    now = datetime.utcnow()
    next_run_at = croniter(cron_expr, now).get_next(datetime)

    async with get_async_session() as session:
        task = ScheduledTask(
            id=uuid.uuid4(),
            user_id=current_user.user_id,
            title=payload.query[:500],
            query=payload.query,
            cron_expression=cron_expr,
            timezone=payload.timezone,
            channel_type=payload.channel_type,
            channel_id=payload.channel_id,
            is_active=True,
            next_run_at=next_run_at,
            run_count=0,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        logger.info(
            "Scheduled task created: %s (user=%s, cron=%s, next=%s)",
            task.id,
            current_user.user_id,
            cron_expr,
            next_run_at.isoformat(),
        )

        return _to_response(task, description)


@router.get(
    "",
    response_model=List[ScheduledTaskResponse],
    summary="내 스케줄 목록",
)
async def list_scheduled_tasks(
    active_only: bool = False,
    current_user: User = Depends(get_current_user),
):
    """현재 사용자의 스케줄 태스크 목록을 반환한다."""
    async with get_async_session() as session:
        stmt = select(ScheduledTask).where(
            ScheduledTask.user_id == current_user.user_id
        )
        if active_only:
            stmt = stmt.where(ScheduledTask.is_active == True)
        stmt = stmt.order_by(ScheduledTask.created_at.desc())

        tasks = (await session.scalars(stmt)).all()
        return [_to_response(t) for t in tasks]


@router.get(
    "/{task_id}",
    response_model=ScheduledTaskResponse,
    summary="스케줄 상세",
)
async def get_scheduled_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """단일 스케줄 태스크 상세 정보를 반환한다."""
    async with get_async_session() as session:
        task = await _get_task_or_404(session, task_id, current_user.user_id)
        return _to_response(task)


@router.patch(
    "/{task_id}",
    response_model=ScheduledTaskResponse,
    summary="스케줄 수정 (활성화/비활성화)",
)
async def update_scheduled_task(
    task_id: str,
    payload: ScheduledTaskUpdate,
    current_user: User = Depends(get_current_user),
):
    """스케줄 태스크를 수정한다. is_active 토글로 일시정지/재활성화가 가능하다."""
    from croniter import croniter

    async with get_async_session() as session:
        task = await _get_task_or_404(session, task_id, current_user.user_id)

        if payload.is_active is not None:
            task.is_active = payload.is_active

        if payload.cron_expression is not None:
            if not validate_cron_expression(payload.cron_expression):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"유효하지 않은 cron 표현식: {payload.cron_expression}",
                )
            task.cron_expression = payload.cron_expression
            # 다음 실행 시각 재계산
            now = datetime.utcnow()
            task.next_run_at = croniter(payload.cron_expression, now).get_next(datetime)

        await session.commit()
        await session.refresh(task)

        return _to_response(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="스케줄 삭제",
)
async def delete_scheduled_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """스케줄 태스크를 영구 삭제한다. 일시정지는 PATCH is_active=false를 사용."""
    async with get_async_session() as session:
        task = await _get_task_or_404(session, task_id, current_user.user_id)
        await session.delete(task)
        await session.commit()

        logger.info("Scheduled task deleted: %s (user=%s)", task_id, current_user.user_id)


# ============================================================================
# 헬퍼 함수
# ============================================================================

async def _get_task_or_404(session, task_id: str, user_id: str) -> ScheduledTask:
    """task_id로 태스크를 조회하며 소유권을 검증한다."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"유효하지 않은 task_id 형식: {task_id}",
        )

    task = await session.get(ScheduledTask, task_uuid)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"스케줄 태스크를 찾을 수 없습니다: {task_id}",
        )
    if task.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 스케줄 태스크에 대한 접근 권한이 없습니다.",
        )
    return task


def _to_response(task: ScheduledTask, description: str = "") -> ScheduledTaskResponse:
    return ScheduledTaskResponse(
        id=str(task.id),
        title=task.title,
        query=task.query,
        cron_expression=task.cron_expression,
        timezone=task.timezone or "UTC",
        channel_type=task.channel_type or "api",
        channel_id=task.channel_id,
        is_active=task.is_active,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        run_count=task.run_count or 0,
        last_error=task.last_error,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
