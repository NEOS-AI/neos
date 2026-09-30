"""상시 에이전트 API -- 트랙 Q13b (docs/Q13_STANDING_AGENT_DESIGN_260930.md §7).

- 경로는 처음부터 `{agent_id}` 를 받고 목록은 처음부터 배열이다 -- 사용자당
  하나(결정 6)를 넘어설 때 API 가 깨지지 않게.
- `/me` 는 편의 별칭이다. `/{agent_id}` 보다 **먼저** 선언해야 id 로 잡히지 않는다.
- 하나를 찾는 조회는 전부 `resolve_agent` 를 거친다. 남의 에이전트는 없는 것과
  똑같이 404 다(존재를 확인해 주지 않는다).
- 만들면 자기소개 background 태스크를 연다(Q13f, `neos/standing/onboarding.py`).
- `/{agent_id}/activity` 는 활동 피드(Q13d, `neos/standing/activity.py`)다.
- 플래그(`standing_agents.enabled`)가 꺼져 있으면 `main.py` 가 이 라우터를
  마운트하지 않는다 -- 거절하는 라우트가 아니라 라우트가 없다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from neos.api.dependencies.auth import get_current_user
from neos.api.models.coding_models import CodingEventResponse, event_response
from neos.database.connection import db_manager
from neos.database.models import User
from neos.standing.activity import (
    MAX_LIMIT,
    ActivitySource,
    PostgresActivitySource,
    agent_activity,
)
from neos.standing.onboarding import available_channels, skill_lines, start_onboarding
from neos.standing.models import StandingAgent, StandingAgentConflict, StandingAgentStatus
from neos.standing.resolve import resolve_agent
from neos.standing.store import PostgresStandingAgentStore, StandingAgentStore
from neos.standing.tasks import TaskOpener

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/standing-agents", tags=["Standing Agents"])


def get_standing_agent_store() -> StandingAgentStore:
    return PostgresStandingAgentStore(db_manager.get_session)


def get_activity_source() -> ActivitySource:
    return PostgresActivitySource(db_manager.get_session)


def get_task_opener() -> TaskOpener:
    """The coding service the self-introduction opens its task in (Q13f).
    Imported late: the coding runtime is heavy and this module is mounted
    only when the feature is on."""
    from neos.coding.runtime import coding_service

    return coding_service


def get_onboarding_inventory(user_id: str) -> tuple[list[str], list[str]]:
    """(channels, skills) the self-introduction may mention -- names only."""
    from neos.config.settings import settings
    from neos.skills.markdown_catalog import list_skills

    return available_channels(user_id, settings.config.channels), skill_lines(list_skills())


def get_inventory_reader():
    return get_onboarding_inventory


class StandingAgentOut(BaseModel):
    agent_id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    #: 자기소개 태스크(Q13f). 열지 못했으면 None -- 에이전트는 그래도 만들어진다.
    onboarding_task_id: str | None = None


class ActivityOut(BaseModel):
    events: list[CodingEventResponse]
    #: 다음 요청의 `after`. 빈 쪽이면 받은 커서 그대로다.
    next: str


class CreateStandingAgentIn(BaseModel):
    name: str


class UpdateStandingAgentIn(BaseModel):
    name: str | None = None
    status: Literal["active", "paused", "retired"] | None = Field(default=None)

    @model_validator(mode="after")
    def something_to_apply(self) -> "UpdateStandingAgentIn":
        if self.name is None and self.status is None:
            raise ValueError("name 또는 status 중 하나는 있어야 한다")
        return self


def _out(agent: StandingAgent) -> StandingAgentOut:
    return StandingAgentOut(
        agent_id=agent.agent_id,
        name=agent.name,
        status=agent.status.value,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        onboarding_task_id=agent.onboarding_task_id,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="standing agent not found")


def _conflict(error: StandingAgentConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": error.reason})


def _unprocessable(error: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


@router.post("", response_model=StandingAgentOut, status_code=status.HTTP_201_CREATED)
async def create_standing_agent(
    body: CreateStandingAgentIn,
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
    coding: TaskOpener = Depends(get_task_opener),
    inventory=Depends(get_inventory_reader),
) -> StandingAgentOut:
    try:
        agent = await store.create(current_user.user_id, body.name)
    except StandingAgentConflict as error:
        raise _conflict(error) from error
    except ValueError as error:
        raise _unprocessable(error) from error
    # 자기소개(Q13f, 설계 결정 1: 명시적으로 만들 때만). 실패해도 에이전트는 남는다.
    try:
        channels, skills = inventory(agent.owner_id)
        await start_onboarding(store, coding, agent, channels=channels, skills=skills)
        agent = await store.get_owned(agent.owner_id, agent.agent_id) or agent
    except Exception:
        logger.exception("standing agent onboarding did not start agent_id=%s", agent.agent_id)
    return _out(agent)


@router.get("", response_model=list[StandingAgentOut])
async def list_standing_agents(
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
) -> list[StandingAgentOut]:
    return [_out(agent) for agent in await store.list_for_owner(current_user.user_id)]


@router.get("/me", response_model=StandingAgentOut)
async def get_my_standing_agent(
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
) -> StandingAgentOut:
    agent = await resolve_agent(store, current_user.user_id)
    if agent is None:
        raise _not_found()
    return _out(agent)


@router.get("/{agent_id}", response_model=StandingAgentOut)
async def get_standing_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
) -> StandingAgentOut:
    agent = await resolve_agent(store, current_user.user_id, agent_id)
    if agent is None:
        raise _not_found()
    return _out(agent)


@router.get("/{agent_id}/activity", response_model=ActivityOut)
async def get_standing_agent_activity(
    agent_id: str,
    after: str | None = Query(None, description="직전 응답의 `next`"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
    source: ActivitySource = Depends(get_activity_source),
) -> ActivityOut:
    """에이전트가 연 태스크 전부의 원장 이벤트를 하나로 합친 것 (설계 §7.1)."""
    try:
        page = await agent_activity(
            store,
            source,
            owner_id=current_user.user_id,
            agent_id=agent_id,
            after=after,
            limit=limit,
        )
    except ValueError as error:
        raise _unprocessable(error) from error
    if page is None:
        raise _not_found()
    return ActivityOut(
        events=[CodingEventResponse(**event_response(event)) for event in page.events],
        next=page.next,
    )


@router.patch("/{agent_id}", response_model=StandingAgentOut)
async def update_standing_agent(
    agent_id: str,
    body: UpdateStandingAgentIn,
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
) -> StandingAgentOut:
    try:
        agent = await store.update(
            current_user.user_id,
            agent_id,
            name=body.name,
            status=StandingAgentStatus(body.status) if body.status else None,
        )
    except StandingAgentConflict as error:
        raise _conflict(error) from error
    except ValueError as error:
        raise _unprocessable(error) from error
    if agent is None:
        raise _not_found()
    return _out(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_standing_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    store: StandingAgentStore = Depends(get_standing_agent_store),
) -> Response:
    if not await store.delete(current_user.user_id, agent_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
