from fastapi import APIRouter, Depends, HTTPException, Query, status

from neos.api.dependencies.auth import get_current_user
from neos.api.models.coding_models import (
    CodingEventListResponse,
    CodingSteerRequest,
    CodingSteerResponse,
    CodingTaskResponse,
    CodingTaskSnapshotResponse,
    CreateCodingTaskRequest,
)
from neos.coding.application.run_service import CodingRunService
from neos.coding.application.task_service import CodingTaskService
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.models import CodingTask
from neos.coding.domain.phases import SteeringMode
from neos.coding.runtime import (
    coding_run_service,
    coding_service,
    get_coding_ticket_store,
)
from neos.coding.transport.base import CodingTicketStore
from neos.database.models import User


router = APIRouter(prefix="/coding", tags=["Coding Agent"])


def get_coding_service() -> CodingTaskService:
    return coding_service


def get_ws_ticket_store() -> CodingTicketStore:
    return get_coding_ticket_store()


def get_coding_run_service() -> CodingRunService:
    return coding_run_service


def _task_response(task: CodingTask) -> dict:
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "version": task.version,
        "last_seq": task.last_seq,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def event_response(event: CodingEvent) -> dict:
    return {
        "v": event.version,
        "task_id": event.task_id,
        "seq": event.seq,
        "event_id": event.event_id,
        "type": event.type,
        "ts": event.created_at.isoformat(),
        "payload": dict(event.payload),
        "run_id": event.run_id,
        "turn_id": event.turn_id,
        "tool_call_id": event.tool_call_id,
        "checkpoint_id": event.checkpoint_id,
    }


@router.post(
    "/tasks", response_model=CodingTaskResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_coding_task(
    body: CreateCodingTaskRequest,
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
):
    return _task_response(
        await service.create_task(owner_id=current_user.user_id, prompt=body.prompt)
    )


@router.post(
    "/tasks/{task_id}/steer",
    response_model=CodingSteerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def steer_coding_task(
    task_id: str,
    body: CodingSteerRequest,
    current_user: User = Depends(get_current_user),
    runs: CodingRunService = Depends(get_coding_run_service),
):
    try:
        steering = await runs.steer(
            task_id=task_id,
            owner_id=current_user.user_id,
            instruction=body.instruction,
            mode=SteeringMode(body.mode),
        )
    except CodingTaskNotFound as error:
        raise HTTPException(
            status_code=404, detail="Coding task not found"
        ) from error
    return {"steering_id": steering.steering_id, "mode": steering.mode.value}


@router.get("/tasks/{task_id}/snapshot", response_model=CodingTaskSnapshotResponse)
async def get_coding_task_snapshot(
    task_id: str,
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
):
    snapshot = await service.snapshot(task_id, current_user.user_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Coding task not found")
    return {"task": _task_response(snapshot.task), "head_seq": snapshot.head_seq}


@router.get("/tasks/{task_id}/events", response_model=CodingEventListResponse)
async def list_coding_events(
    task_id: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
):
    snapshot = await service.snapshot(task_id, current_user.user_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Coding task not found")
    events = await service.events.list_after(task_id, after_seq=after_seq, limit=limit)
    return {
        "head_seq": snapshot.head_seq,
        "events": [event_response(event) for event in events],
    }


@router.post("/tasks/{task_id}/ws-ticket", status_code=status.HTTP_201_CREATED)
async def create_coding_ws_ticket(
    task_id: str,
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
    tickets: CodingTicketStore = Depends(get_ws_ticket_store),
):
    if await service.snapshot(task_id, current_user.user_id) is None:
        raise HTTPException(status_code=404, detail="Coding task not found")
    ticket = await tickets.issue(owner_id=current_user.user_id, task_id=task_id)
    return {"ticket": ticket, "expires_in": tickets.expires_in}
