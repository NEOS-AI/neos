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
