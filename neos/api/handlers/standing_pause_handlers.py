"""멈춘 태스크의 재개와 소유자 알림 대상 -- 트랙 Q10b
(docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §2 · §4).

두 라우터다.

- `resume_router` -- `POST /coding/tasks/{task_id}/resume`. **사람만** 쓴다: 소유자 인증
  라우트이고 어떤 도구도 이 길에 닿지 않는다. 멈추지 않은 태스크는 409
  `task_not_paused`, 남의 태스크는 다른 코딩 라우트와 같은 404 다.
  태스크를 멈출 수 있는 쪽이 하나라도 있으면 마운트한다(`resume_route_mounted`) --
  봉투(Q10b, `standing_agents.enabled`)와 감시자 집행(Q5b, `jev.monitor.enforce`).
  감시자는 에이전트 태스크만이 아니라 모든 태스크를 멈추므로 상시 에이전트가 꺼져
  있어도 재개 라우트가 있어야 한다. 멈출 수 없는 앱에는 라우트가 없다.
- `notify_router` -- `GET/PUT/DELETE /standing-agents/{agent_id}/notify-target`. 에이전트의
  알림이 갈 채널 하나. `standing_agents.notifications.enabled` 일 때 마운트한다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.coding_handlers import get_coding_run_service
from neos.coding.application.run_service import CodingRunService
from neos.coding.domain.errors import CodingTaskNotFound
from neos.database.connection import db_manager
from neos.database.models import User
from neos.standing.notifications import (
    NotificationStore,
    NotifyTarget,
    PostgresNotificationStore,
)

def resume_route_mounted(config) -> bool:
    """재개 라우트가 있어야 하는가 -- 태스크를 `PAUSED` 로 보낼 수 있는 쪽이 있는가.

    `neos/main.py` 가 이 함수 하나로 정한다. 멈추는 쪽을 새로 더하면 여기에 더한다:
    멈출 수 있는데 재개할 길이 없으면 멈춤이 덫이 된다(Q10b P8 과 같은 이유).
    """
    return bool(config.standing_agents.enabled or config.jev.monitor.enforce)


resume_router = APIRouter(prefix="/coding", tags=["Coding Agent"])
notify_router = APIRouter(prefix="/standing-agents", tags=["Standing Agents"])


class CodingResumeResponse(BaseModel):
    task_id: str
    status: Literal["running"]


class NotifyTargetIn(BaseModel):
    channel_type: Literal["slack", "discord", "telegram"]
    channel_id: str


class NotifyTargetOut(BaseModel):
    channel_type: str
    channel_id: str


def get_notification_store() -> NotificationStore:
    return PostgresNotificationStore(db_manager.get_session)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


@resume_router.post(
    "/tasks/{task_id}/resume",
    response_model=CodingResumeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_coding_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    runs: CodingRunService = Depends(get_coding_run_service),
):
    try:
        commit = await runs.resume(task_id=task_id, owner_id=current_user.user_id)
    except CodingTaskNotFound as error:
        raise _not_found() from error
    if commit is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="task_not_paused")
    return {"task_id": task_id, "status": "running"}


@notify_router.get("/{agent_id}/notify-target", response_model=NotifyTargetOut)
async def get_notify_target(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    store: NotificationStore = Depends(get_notification_store),
):
    target = await store.get_target(current_user.user_id, agent_id)
    if target is None:
        raise _not_found()
    return {"channel_type": target.channel_type, "channel_id": target.channel_id}


@notify_router.put("/{agent_id}/notify-target", response_model=NotifyTargetOut)
async def put_notify_target(
    agent_id: str,
    body: NotifyTargetIn,
    current_user: User = Depends(get_current_user),
    store: NotificationStore = Depends(get_notification_store),
):
    try:
        target = NotifyTarget(body.channel_type, body.channel_id.strip())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    if not await store.set_target(current_user.user_id, agent_id, target):
        raise _not_found()
    return {"channel_type": target.channel_type, "channel_id": target.channel_id}


@notify_router.delete("/{agent_id}/notify-target", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notify_target(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    store: NotificationStore = Depends(get_notification_store),
):
    if not await store.clear_target(current_user.user_id, agent_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
