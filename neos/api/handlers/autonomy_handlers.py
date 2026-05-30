"""Agent autonomy preference API handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from neos.api.dependencies.auth import get_current_user
from neos.api.services.workflow_service import WorkflowService
from neos.database.connection import db_manager
from neos.database.models import User

router = APIRouter(prefix="/autonomy", tags=["Agent Autonomy"])

_DESCRIPTIONS = {
    0: "수동 - 모든 에이전트 액션 승인 필요",
    1: "요청 - 위험 작업만 승인 필요",
    2: "완전 자율 - 모든 액션 자동 처리",
}


class AutonomyPreferenceResponse(BaseModel):
    user_id: str
    autonomy_level: int
    description: str


class UpdateAutonomyRequest(BaseModel):
    autonomy_level: int = Field(..., ge=0, le=2)


@router.get("/preference", response_model=AutonomyPreferenceResponse)
async def get_autonomy_preference(
    current_user: User = Depends(get_current_user),
) -> AutonomyPreferenceResponse:
    prefs = current_user.preferences or {}
    level = WorkflowService.resolve_autonomy_level(prefs)

    return AutonomyPreferenceResponse(
        user_id=current_user.user_id,
        autonomy_level=level,
        description=_DESCRIPTIONS[level],
    )


@router.put("/preference", response_model=AutonomyPreferenceResponse)
async def update_autonomy_preference(
    body: UpdateAutonomyRequest,
    current_user: User = Depends(get_current_user),
) -> AutonomyPreferenceResponse:
    try:
        await db_manager.execute(
            """
            UPDATE users
            SET preferences = jsonb_set(
                COALESCE(preferences, '{}'::jsonb),
                '{autonomy_level}',
                $1::jsonb,
                TRUE
            ),
            updated_at = NOW()
            WHERE user_id = $2
            """,
            str(body.autonomy_level),
            current_user.user_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"선호도 업데이트 실패: {exc}",
        ) from exc

    return AutonomyPreferenceResponse(
        user_id=current_user.user_id,
        autonomy_level=body.autonomy_level,
        description=_DESCRIPTIONS[body.autonomy_level],
    )
