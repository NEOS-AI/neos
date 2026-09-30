from fastapi import APIRouter, Depends, HTTPException, Query, status

from neos.api.dependencies.auth import get_current_user
from neos.api.models.coding_models import event_response  # noqa: F401 -- coding_ws_handlers imports it from here
from neos.api.models.coding_models import (
    CodingApprovalDecisionRequest,
    CodingApprovalSnapshot,
    CodingCommandCatalogResponse,
    CodingCommandRequest,
    CodingCommandResponse,
    CodingEventListResponse,
    CodingSteerRequest,
    CodingSteerResponse,
    CodingStopResponse,
    CodingTaskListResponse,
    CodingTaskResponse,
    CodingProjectionSnapshotResponse,
    CodingSandboxStatusResponse,
    CodingWorkspaceDiffResponse,
    CodingWorkspaceFileResponse,
    CodingWorkspaceFileSaveRequest,
    CodingWorkspaceFileSaveResponse,
    CodingWorkspaceTreeResponse,
    CreateCodingTaskRequest,
)
from neos.coding.application.approval_service import CodingApprovalService
from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalNotFound,
)
from neos.coding.application.run_service import CodingRunService
from neos.coding.commands import CodingCommandService, catalog_listings
from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.application.workspace_service import CodingWorkspaceService
from neos.coding.application.task_service import (
    CodingTaskService,
    clamp_task_list_limit,
)
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.models import CodingTaskMode
from neos.coding.domain.models import CodingTask
from neos.coding.domain.phases import SteeringMode
from neos.coding.domain.workspace_edits import WorkspaceEditConflict
from neos.coding.managed.admin import ManagedSandboxStatusService
from neos.coding.runtime import (
    coding_run_service,
    coding_approval_service,
    coding_command_service,
    coding_service,
    coding_snapshot_service,
    coding_workspace_service,
    managed_sandbox_status_service,
    get_coding_ticket_store,
    get_workspace_ticket_store,
)
from neos.coding.transport.base import CodingTicketStore
from neos.coding.transport.workspace_tickets import (
    WorkspaceStreamKind,
    WorkspaceTicketStore,
)
from neos.database.models import User


router = APIRouter(prefix="/coding", tags=["Coding Agent"])


def get_coding_service() -> CodingTaskService:
    return coding_service


def get_ws_ticket_store() -> CodingTicketStore:
    return get_coding_ticket_store()


def get_coding_run_service() -> CodingRunService:
    return coding_run_service


def get_coding_command_service() -> CodingCommandService:
    return coding_command_service


def get_coding_snapshot_service() -> CodingSnapshotService:
    return coding_snapshot_service


def get_coding_approval_service() -> CodingApprovalService:
    return coding_approval_service


def get_coding_workspace_service() -> CodingWorkspaceService:
    return coding_workspace_service


def get_workspace_stream_ticket_store() -> WorkspaceTicketStore:
    return get_workspace_ticket_store()


def get_managed_sandbox_service() -> ManagedSandboxStatusService:
    return managed_sandbox_status_service()


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _task_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=_error_detail("coding_task_not_found", "Coding task not found"),
    )


_WORKSPACE_CONFLICT_CODES = {
    "workspace_revision_conflict",
    "workspace_edit_exists",
    "workspace_edit_reconcile_required",
    "workspace_run_changed",
    "workspace_run_not_running",
}


def _workspace_message(code: str) -> str:
    return f"Coding {code.replace('_', ' ')}"


def _raise_workspace_error(error: WorkspaceEditConflict) -> None:
    code = str(error)
    detail = _error_detail(code, _workspace_message(code))
    if code == "workspace_not_found":
        raise HTTPException(status_code=404, detail=detail) from error
    if code in _WORKSPACE_CONFLICT_CODES:
        raise HTTPException(status_code=409, detail=detail) from error
    raise HTTPException(status_code=422, detail=detail) from error


def _approval_response(approval) -> dict:
    return {
        "approval_id": approval.approval_id,
        "tool_name": approval.tool_name,
        "risk": approval.risk.value,
        "status": approval.status.value,
        "requested_at": approval.requested_at,
        "expires_at": approval.expires_at,
        "display_summary": dict(approval.display_summary),
    }


_LIST_PROMPT_MAX = 160


def _task_response(task: CodingTask) -> dict:
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "version": task.version,
        "last_seq": task.last_seq,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _list_item(task: CodingTask) -> dict:
    prompt = task.prompt
    if len(prompt) > _LIST_PROMPT_MAX:
        prompt = prompt[:_LIST_PROMPT_MAX]
    return {**_task_response(task), "prompt": prompt}


@router.post(
    "/tasks", response_model=CodingTaskResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_coding_task(
    body: CreateCodingTaskRequest,
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
):
    return _task_response(
        await service.create_task(
            owner_id=current_user.user_id,
            prompt=body.prompt,
            mode=CodingTaskMode(body.mode),
        )
    )


@router.get("/tasks", response_model=CodingTaskListResponse)
async def list_coding_tasks(
    limit: int = Query(20),
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
):
    tasks = await service.list_owned(
        current_user.user_id, limit=clamp_task_list_limit(limit)
    )
    return {"tasks": [_list_item(task) for task in tasks]}


@router.get("/commands", response_model=CodingCommandCatalogResponse)
async def list_coding_commands(
    current_user: User = Depends(get_current_user),
):
    del current_user
    return {"commands": list(catalog_listings())}


@router.post(
    "/tasks/{task_id}/commands",
    response_model=CodingCommandResponse,
)
async def invoke_coding_command(
    task_id: str,
    body: CodingCommandRequest,
    current_user: User = Depends(get_current_user),
    commands: CodingCommandService = Depends(get_coding_command_service),
):
    from neos.coding.commands.types import CommandStatus

    try:
        result = await commands.invoke(
            text=body.text,
            task_id=task_id,
            owner_id=current_user.user_id,
        )
    except CodingTaskNotFound as error:
        raise _task_not_found() from error
    if result.status is CommandStatus.UNKNOWN:
        raise HTTPException(
            status_code=400,
            detail=_error_detail("unknown_coding_command", result.message),
        )
    if result.status is CommandStatus.CHAT:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "not_a_slash_command",
                "Request text is not a slash command",
            ),
        )
    return result.as_mapping()


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
        raise _task_not_found() from error
    return {"steering_id": steering.steering_id, "mode": steering.mode.value}


@router.post(
    "/tasks/{task_id}/stop",
    response_model=CodingStopResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stop_coding_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    runs: CodingRunService = Depends(get_coding_run_service),
):
    try:
        await runs.stop(task_id=task_id, owner_id=current_user.user_id)
    except CodingTaskNotFound as error:
        raise _task_not_found() from error
    return {"task_id": task_id, "status": "cancelled"}


@router.post(
    "/tasks/{task_id}/approvals/{approval_id}",
    response_model=CodingApprovalSnapshot,
)
async def resolve_coding_approval(
    task_id: str,
    approval_id: str,
    body: CodingApprovalDecisionRequest,
    current_user: User = Depends(get_current_user),
    approvals: CodingApprovalService = Depends(get_coding_approval_service),
):
    try:
        commit = await approvals.resolve(
            task_id=task_id,
            approval_id=approval_id,
            owner_id=current_user.user_id,
            decision=ApprovalDecision(body.decision),
            answers=tuple(body.answers),
            remember=body.remember,
        )
    except ApprovalNotFound as error:
        raise HTTPException(
            status_code=404,
            detail=_error_detail(
                "coding_approval_not_found",
                "Coding approval not found",
            ),
        ) from error
    except ApprovalConflict as error:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "coding_approval_conflict",
                "Coding approval cannot be resolved",
            ),
        ) from error
    return _approval_response(commit.approval)


@router.get(
    "/tasks/{task_id}/snapshot", response_model=CodingProjectionSnapshotResponse
)
async def get_coding_task_snapshot(
    task_id: str,
    current_user: User = Depends(get_current_user),
    snapshots: CodingSnapshotService = Depends(get_coding_snapshot_service),
):
    snapshot = await snapshots.get_owned(task_id, current_user.user_id)
    if snapshot is None:
        raise _task_not_found()
    return snapshot


@router.get(
    "/tasks/{task_id}/sandbox-status",
    response_model=CodingSandboxStatusResponse,
)
async def get_coding_sandbox_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    sandboxes: ManagedSandboxStatusService = Depends(get_managed_sandbox_service),
):
    """소유자에게 보이는 샌드박스 상태.

    비소유자와 "샌드박스 없음"이 **같은 404**다. 둘을 구별하면 남의 태스크가
    존재한다는 사실이 샌다 -- 소유권 검사는 조회 질의 안에 있다
    (`PostgresManagedSandboxRepository.read_owner_sandbox`).
    """
    status_view = await sandboxes.owner_status(
        task_id=task_id, owner_id=current_user.user_id
    )
    if status_view is None:
        raise HTTPException(
            status_code=404,
            detail=_error_detail(
                "coding_sandbox_not_found",
                "Coding sandbox not found",
            ),
        )
    return status_view.to_payload()


@router.get(
    "/tasks/{task_id}/workspace/tree",
    response_model=CodingWorkspaceTreeResponse,
)
async def get_coding_workspace_tree(
    task_id: str,
    path: str = Query("."),
    current_user: User = Depends(get_current_user),
    workspace: CodingWorkspaceService = Depends(get_coding_workspace_service),
):
    try:
        return await workspace.list_tree(
            task_id=task_id,
            owner_id=current_user.user_id,
            path=path,
        )
    except WorkspaceEditConflict as error:
        _raise_workspace_error(error)


@router.get(
    "/tasks/{task_id}/workspace/files",
    response_model=CodingWorkspaceFileResponse,
)
async def get_coding_workspace_file(
    task_id: str,
    path: str = Query(..., min_length=1, max_length=4096),
    current_user: User = Depends(get_current_user),
    workspace: CodingWorkspaceService = Depends(get_coding_workspace_service),
):
    try:
        return await workspace.read_file(
            task_id=task_id,
            owner_id=current_user.user_id,
            path=path,
        )
    except WorkspaceEditConflict as error:
        _raise_workspace_error(error)


@router.get(
    "/tasks/{task_id}/workspace/diff",
    response_model=CodingWorkspaceDiffResponse,
)
async def get_coding_workspace_diff(
    task_id: str,
    staged: bool = Query(False),
    current_user: User = Depends(get_current_user),
    workspace: CodingWorkspaceService = Depends(get_coding_workspace_service),
):
    try:
        return await workspace.git_diff(
            task_id=task_id,
            owner_id=current_user.user_id,
            staged=staged,
        )
    except WorkspaceEditConflict as error:
        _raise_workspace_error(error)


@router.put(
    "/tasks/{task_id}/workspace/files",
    response_model=CodingWorkspaceFileSaveResponse,
)
async def save_coding_workspace_file(
    task_id: str,
    body: CodingWorkspaceFileSaveRequest,
    current_user: User = Depends(get_current_user),
    workspace: CodingWorkspaceService = Depends(get_coding_workspace_service),
):
    try:
        return await workspace.save_file(
            task_id=task_id,
            owner_id=current_user.user_id,
            edit_id=body.edit_id,
            path=body.path,
            base_revision=body.base_revision,
            content=body.content,
        )
    except WorkspaceEditConflict as error:
        _raise_workspace_error(error)


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
        raise _task_not_found()
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
        raise _task_not_found()
    ticket = await tickets.issue(owner_id=current_user.user_id, task_id=task_id)
    return {"ticket": ticket, "expires_in": tickets.expires_in}


@router.post(
    "/tasks/{task_id}/workspace/ws-ticket",
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_ws_ticket(
    task_id: str,
    kind: WorkspaceStreamKind = Query(...),
    current_user: User = Depends(get_current_user),
    service: CodingTaskService = Depends(get_coding_service),
    tickets: WorkspaceTicketStore = Depends(get_workspace_stream_ticket_store),
):
    if await service.snapshot(task_id, current_user.user_id) is None:
        raise _task_not_found()
    ticket = await tickets.issue(
        owner_id=current_user.user_id,
        task_id=task_id,
        kind=kind,
    )
    return {"ticket": ticket, "expires_in": tickets.expires_in, "kind": kind.value}
