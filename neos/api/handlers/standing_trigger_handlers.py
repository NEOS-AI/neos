"""상시 에이전트 트리거 API -- 트랙 Q4a (docs/Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md §2).

두 라우터다.

- `router` -- 소유자가 트리거를 만들고 보고 끄고 지운다. 코딩 핸들러와 같은 인증
  의존성을 문다. 에이전트는 `resolve_agent` 로만 찾고, 남의 것은 404 다.
- `delivery_router` -- 바깥 세계가 배달한다. **인증 의존성이 없다** -- 서명이 인증이다.
  모르는 트리거·틀린 서명·창 밖 시각·모양이 틀린 헤더는 전부 **같은 401** 이다
  (트리거가 있는지 확인해 주지 않는다). 본문 상한은 서명을 보기 전에 413 이다.
  서명이 맞으면 결과와 상관없이 202 이고 본문이 결과를 말한다.

webhook 비밀은 만들 때 **한 번만** 응답에 싣는다. 비밀은 저장하지 않고 마스터 키에서
파생하므로(`trigger_secret`) 다시 보여 줄 수도 있지만, 보여 주는 길이 하나면 새는
길도 하나다.

`standing_agents.enabled` 와 `standing_agents.triggers.enabled` 가 둘 다 켜져야
`main.py` 가 두 라우터를 마운트한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from neos.api.channels.inbound_idempotency import (
    ChannelInboundIdempotencyStore,
    PostgresChannelInboundIdempotencyStore,
)
from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.standing_agent_handlers import (
    get_envelope,
    get_standing_agent_store,
    get_task_opener,
)
from neos.database.connection import db_manager
from neos.database.models import User
from neos.standing.budget import AgentBudgetEnvelope
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore
from neos.standing.tasks import TaskOpener
from neos.standing.triggers import (
    PostgresTriggerStore,
    StandingTrigger,
    TriggerStore,
    create_trigger,
    filters_json,
    fire_trigger,
    parse_filters,
    trigger_secret,
    verify_delivery,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/standing-agents", tags=["Standing Agent Triggers"])
delivery_router = APIRouter(prefix="/standing-triggers", tags=["Standing Agent Triggers"])


def get_trigger_store() -> TriggerStore:
    return PostgresTriggerStore(db_manager.get_session)


def get_idempotency_store() -> ChannelInboundIdempotencyStore:
    return PostgresChannelInboundIdempotencyStore(db_manager.get_session)


def get_trigger_settings() -> tuple[str, int, int]:
    """(마스터 키, 본문 상한, 시각 허용 초). 키는 설정 검증기가 이미 요구했다."""
    from neos.config.settings import settings

    config = settings.config
    triggers = config.standing_agents.triggers
    return (
        config.secrets.standing_trigger_signing_key or "",
        triggers.max_body_bytes,
        triggers.timestamp_tolerance_seconds,
    )


def get_clock():
    return lambda: datetime.now(UTC)


class TriggerOut(BaseModel):
    trigger_id: str
    agent_id: str
    source: str
    prompt_template: str
    filters: list[dict[str, Any]]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CreatedTriggerOut(TriggerOut):
    #: 만들 때 한 번만 싣는다.
    secret: str
    #: 배달할 경로. API 접두를 포함한다.
    delivery_path: str


class CreateTriggerIn(BaseModel):
    prompt_template: str
    filters: list[dict[str, Any]] = []


class UpdateTriggerIn(BaseModel):
    enabled: bool | None = None
    prompt_template: str | None = None
    filters: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def something_to_apply(self) -> "UpdateTriggerIn":
        if self.enabled is None and self.prompt_template is None and self.filters is None:
            raise ValueError("enabled · prompt_template · filters 중 하나는 있어야 한다")
        return self


def _out(trigger: StandingTrigger) -> TriggerOut:
    return TriggerOut(
        trigger_id=trigger.trigger_id,
        agent_id=trigger.agent_id,
        source=trigger.source,
        prompt_template=trigger.prompt_template,
        filters=filters_json(trigger.filters),
        enabled=trigger.enabled,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="trigger not found")


def _delivery_path(trigger_id: str) -> str:
    from neos.config.settings import settings

    return f"{settings.API_V1_PREFIX}/standing-triggers/{trigger_id}/deliveries"


@router.post(
    "/{agent_id}/triggers",
    response_model=CreatedTriggerOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_standing_trigger(
    agent_id: str,
    body: CreateTriggerIn,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    triggers: TriggerStore = Depends(get_trigger_store),
    trigger_settings: tuple[str, int, int] = Depends(get_trigger_settings),
) -> CreatedTriggerOut:
    try:
        filters = parse_filters(body.filters)
        trigger = await create_trigger(
            agents,
            triggers,
            owner_id=current_user.user_id,
            agent_id=agent_id,
            prompt_template=body.prompt_template,
            filters=filters,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="standing agent not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if trigger is None:
        raise HTTPException(status_code=404, detail="standing agent not found")
    master_key = trigger_settings[0]
    return CreatedTriggerOut(
        **_out(trigger).model_dump(),
        secret=trigger_secret(master_key, trigger.trigger_id),
        delivery_path=_delivery_path(trigger.trigger_id),
    )


@router.get("/{agent_id}/triggers", response_model=list[TriggerOut])
async def list_standing_triggers(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    triggers: TriggerStore = Depends(get_trigger_store),
) -> list[TriggerOut]:
    # 남의 에이전트면 빈 목록이 아니라 404 다 -- 빈 목록은 "에이전트는 있다"는 뜻이 된다.
    agent = await resolve_agent(agents, current_user.user_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="standing agent not found")
    return [_out(t) for t in await triggers.list_for_agent(agent.owner_id, agent.agent_id)]


@router.patch("/{agent_id}/triggers/{trigger_id}", response_model=TriggerOut)
async def update_standing_trigger(
    agent_id: str,
    trigger_id: str,
    body: UpdateTriggerIn,
    current_user: User = Depends(get_current_user),
    triggers: TriggerStore = Depends(get_trigger_store),
) -> TriggerOut:
    try:
        filters = parse_filters(body.filters) if body.filters is not None else None
        trigger = await _owned_under(triggers, current_user.user_id, agent_id, trigger_id)
        if trigger is not None:
            trigger = await triggers.update(
                current_user.user_id,
                trigger_id,
                enabled=body.enabled,
                prompt_template=body.prompt_template,
                filters=filters,
            )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if trigger is None:
        raise _not_found()
    return _out(trigger)


@router.delete("/{agent_id}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_standing_trigger(
    agent_id: str,
    trigger_id: str,
    current_user: User = Depends(get_current_user),
    triggers: TriggerStore = Depends(get_trigger_store),
) -> Response:
    if await _owned_under(triggers, current_user.user_id, agent_id, trigger_id) is None:
        raise _not_found()
    if not await triggers.delete(current_user.user_id, trigger_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _owned_under(
    triggers: TriggerStore, owner_id: str, agent_id: str, trigger_id: str
) -> StandingTrigger | None:
    """경로의 에이전트 밑에 있는 트리거만. 다른 에이전트의 트리거 id 로 이 경로를 쓰지 못한다."""
    trigger = await triggers.get_owned(owner_id, trigger_id)
    return trigger if trigger is not None and trigger.agent_id == agent_id else None


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="invalid signature")


@delivery_router.post("/{trigger_id}/deliveries", status_code=status.HTTP_202_ACCEPTED)
async def deliver_to_trigger(
    trigger_id: str,
    request: Request,
    x_neos_timestamp: str = Header(default=""),
    x_neos_delivery: str = Header(default=""),
    x_neos_signature: str = Header(default=""),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    triggers: TriggerStore = Depends(get_trigger_store),
    coding: TaskOpener = Depends(get_task_opener),
    idempotency: ChannelInboundIdempotencyStore = Depends(get_idempotency_store),
    envelope: AgentBudgetEnvelope | None = Depends(get_envelope),
    trigger_settings: tuple[str, int, int] = Depends(get_trigger_settings),
    clock=Depends(get_clock),
) -> JSONResponse:
    master_key, max_body, tolerance = trigger_settings
    body = await _read_capped(request, max_body)
    trigger = await triggers.get_for_delivery(trigger_id)
    # 모르는 트리거도 서명을 검사하는 것처럼 같은 일을 한다 -- 응답 시간으로도 있고 없음이
    # 갈리지 않게. 비교할 비밀은 아무도 모르는 값이다.
    secret = trigger_secret(master_key, trigger_id if trigger is not None else "\x00unknown")
    if not master_key or not verify_delivery(
        secret,
        timestamp=x_neos_timestamp,
        delivery_id=x_neos_delivery,
        signature=x_neos_signature,
        body=body,
        now=clock(),
        tolerance_seconds=tolerance,
    ):
        raise _unauthorized()
    if trigger is None:
        raise _unauthorized()
    firing = await fire_trigger(
        agents,
        coding,
        idempotency,
        trigger,
        delivery_id=x_neos_delivery,
        body=body,
        envelope=envelope,
    )
    logger.info(
        "standing trigger delivery trigger_id=%s status=%s reason=%s task_id=%s",
        trigger_id,
        firing.status,
        firing.reason,
        firing.task_id,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": firing.status, "task_id": firing.task_id, "reason": firing.reason},
    )


async def _read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="delivery body too large")
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise HTTPException(status_code=413, detail="delivery body too large")
    return bytes(chunks)
