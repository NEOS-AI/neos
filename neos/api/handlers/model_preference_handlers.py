"""사용자 × 모델 선호 API (effort). 설계: docs/MODEL_EFFORT_PREFERENCES_DESIGN.md §6."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.config.model_config import effort_levels_for, model_config
from neos.config.model_identity import canonicalize
from neos.database.models import User
from neos.database.repositories.model_preference_repository import (
    ModelPreferenceRepository,
)

router = APIRouter(prefix="/users/me/model-preferences", tags=["Model Preferences"])


class ModelPreferenceOut(BaseModel):
    model: str
    effort: str
    updated_at: datetime


class EffortIn(BaseModel):
    effort: str


def _pin(raw: str) -> str:
    """gateway id · 은퇴한 핀 · 별칭을 카탈로그 핀으로. 모르면 404.

    `canonicalize` 는 `retired:` 를 apply_remap 과 무관하게 적용한다 -- 은퇴한
    핀으로 들어온 요청은 후계 핀으로 저장된다.
    """
    ident = canonicalize(raw, catalog=model_config.catalog, apply_remap=True)
    if ident is None:
        raise HTTPException(status_code=404, detail=f"unknown model {raw!r}")
    return ident.catalog_id


@router.get("", response_model=list[ModelPreferenceOut])
async def list_model_preferences(
    current_user: User = Depends(get_current_user),
) -> list[ModelPreferenceOut]:
    rows = await ModelPreferenceRepository.list_for_user(current_user.user_id)
    return [
        ModelPreferenceOut(model=r.model_pin, effort=r.effort, updated_at=r.updated_at)
        for r in rows
    ]


@router.put("/{model:path}", response_model=ModelPreferenceOut)
async def put_model_preference(
    model: str,
    body: EffortIn,
    current_user: User = Depends(get_current_user),
) -> ModelPreferenceOut:
    pin = _pin(model)
    allowed = list(effort_levels_for(pin))
    if body.effort not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": f"{pin} does not take {body.effort!r}", "allowed": allowed},
        )
    row = await ModelPreferenceRepository.upsert_effort(
        current_user.user_id, pin, body.effort
    )
    return ModelPreferenceOut(model=row.model_pin, effort=row.effort, updated_at=row.updated_at)


@router.delete("/{model:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_preference(
    model: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    await ModelPreferenceRepository.delete(current_user.user_id, _pin(model))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
