from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateCodingTaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)


class CodingTaskResponse(BaseModel):
    task_id: str
    status: str
    version: int
    last_seq: int
    created_at: datetime
    updated_at: datetime


class CodingEventResponse(BaseModel):
    v: int
    task_id: str
    seq: int
    event_id: str
    type: str
    ts: datetime
    payload: dict[str, Any]
    run_id: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None
    checkpoint_id: str | None = None


class CodingEventListResponse(BaseModel):
    head_seq: int
    events: list[CodingEventResponse]


class CodingPhaseSnapshot(BaseModel):
    phase_id: str
    run_id: str
    kind: str
    attempt: int
    status: str
    started_at: datetime
    completed_at: datetime | None


class CodingRunSnapshot(BaseModel):
    run_id: str
    attempt: int
    status: str
    resume_from_checkpoint_id: str | None


class CodingToolSnapshot(BaseModel):
    tool_call_id: str
    run_id: str
    status: str
    result: dict[str, Any] | None


class CodingApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]


class CodingApprovalSnapshot(BaseModel):
    approval_id: str
    tool_name: str
    risk: Literal["workspace_write", "command"]
    status: Literal["pending", "approved", "denied", "expired", "invalidated"]
    requested_at: datetime
    expires_at: datetime
    display_summary: dict[str, Any]


class CodingTextPartSnapshot(BaseModel):
    part_id: str
    run_id: str
    turn_id: str
    status: Literal["streaming", "completed", "interrupted"]
    content: str
    first_seq: int
    last_seq: int


class CodingWorkspaceSnapshot(BaseModel):
    revision: str
    git_head: str | None
    changed_files: list[str]
    user_edits: list["CodingWorkspaceEditSnapshot"] = Field(default_factory=list)


class CodingWorkspaceEditSnapshot(BaseModel):
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: Literal[
        "pending_agent_sync", "agent_synced", "reconcile_required"
    ]
    applied_checkpoint_id: str | None


class CodingWorkspaceEntryResponse(BaseModel):
    path: str
    kind: str
    size: int
    modified_at: datetime


class CodingWorkspaceTreeResponse(BaseModel):
    entries: list[CodingWorkspaceEntryResponse]
    workspace_revision: str


class CodingWorkspaceFileResponse(BaseModel):
    path: str
    content: str | None
    binary: bool
    size: int
    workspace_revision: str


class CodingWorkspaceDiffResponse(BaseModel):
    content: str
    truncated: bool
    workspace_revision: str


class CodingWorkspaceFileSaveRequest(BaseModel):
    edit_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=4096)
    base_revision: str = Field(min_length=1, max_length=64)
    content: str


class CodingWorkspaceFileSaveResponse(BaseModel):
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str
    status: Literal["pending_agent_sync"]


class CodingCheckpointSnapshot(BaseModel):
    checkpoint_id: str
    run_id: str
    seq: int
    loop_state: dict[str, Any]
    workspace_revision: str
    created_at: datetime


class CodingProjectionSnapshotResponse(BaseModel):
    task: CodingTaskResponse
    active_run: CodingRunSnapshot | None
    phases: list[CodingPhaseSnapshot]
    tools: list[CodingToolSnapshot]
    approvals: list[CodingApprovalSnapshot]
    parts: list[CodingTextPartSnapshot]
    todos: list[dict[str, Any]]
    workspace: CodingWorkspaceSnapshot
    latest_checkpoint: CodingCheckpointSnapshot | None
    head_seq: int
    connection_basis: Literal["checkpoint"]


class CodingSteerRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=100_000)
    mode: Literal["safe_point", "interrupt_now"] = "safe_point"


class CodingSteerResponse(BaseModel):
    steering_id: str
    mode: Literal["safe_point", "interrupt_now"]


class CodingSandboxStatusResponse(BaseModel):
    """소유자에게 나가는 샌드박스 상태.

    **필드가 계약이다.** provider·region·provider 참조·할당 식별자·서킷 상세·
    raw 에러는 여기 없고, 추가하려면 `neos.coding.managed.projection`의
    경계를 먼저 다시 생각해야 한다.
    """

    state: Literal[
        "preparing",
        "ready",
        "suspended",
        "provider_recovery_pending",
        "operator_recovery_required",
        "cleaning_up",
        "cleaned",
    ]
    can_run: bool
    can_open_terminal: bool
    recovered_from_checkpoint: bool
    updated_at: datetime


class CodingSandboxDrainRequest(BaseModel):
    region: str = Field(default="local", min_length=1, max_length=64)
    drained: bool = True


class CodingSandboxDrainResponse(BaseModel):
    provider: str
    region: str
    drained: bool
    circuit: Literal["healthy", "degraded", "unavailable"]
    # 마이그레이션 046 이후 드레인은 클러스터 전체에 걸린다. 이 값이 계약이므로
    # 다시 프로세스 로컬로 되돌리려면 여기부터 바뀌어야 한다.
    scope: Literal["cluster"]


class CodingSandboxCleanupRetryResponse(BaseModel):
    allocation_id: str
    state: str


class CodingSandboxRecoveryRequest(BaseModel):
    """복구 승인 요청.

    체크섬이 승인의 **유일한** 결속 수단이므로 모양 검증을 경계에서 끝낸다 --
    `neos.coding.managed.archive.archive_checksum()`이 내는 정본 표기와 같다.
    """

    archive_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CodingSandboxRecoveryResponse(BaseModel):
    allocation_id: str
    generation: int
    state: str


class CodingSandboxArchiveResponse(BaseModel):
    """아카이브를 뜬 결과. **본문도 경로도 나가지 않는다** -- 식별자와 체크섬뿐이다.

    `checksum` 은 그대로 복구 승인 요청에 넣는 값이다(`sha256:<64 hex>`).
    """

    allocation_id: str
    archive_id: str
    checksum: str
    content_bytes: int
    expires_at: datetime
