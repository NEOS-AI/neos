from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from neos.coding.domain.approvals import ApprovalStatus
from neos.coding.domain.phases import CodingPhaseKind
from neos.coding.domain.text_parts import TextPartStatus
from neos.coding.tools.registry import ToolRisk
from neos.coding.repositories.projection_repository import CodingProjectionRows


@dataclass(frozen=True, slots=True)
class CodingTaskProjection:
    task_id: str
    status: str
    version: int
    last_seq: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CodingRunProjection:
    run_id: str
    attempt: int
    status: str
    resume_from_checkpoint_id: str | None


@dataclass(frozen=True, slots=True)
class CodingPhaseProjection:
    phase_id: str
    run_id: str
    kind: CodingPhaseKind
    attempt: int
    status: str
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CodingToolProjection:
    tool_call_id: str
    run_id: str
    status: str
    result: Mapping[str, Any] | None
    name: str | None = None
    preview: str | None = None


@dataclass(frozen=True, slots=True)
class CodingApprovalProjection:
    approval_id: str
    tool_name: str
    risk: ToolRisk
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    display_summary: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CodingTextPartProjection:
    part_id: str
    run_id: str
    turn_id: str
    status: TextPartStatus
    content: str
    first_seq: int
    last_seq: int


@dataclass(frozen=True, slots=True)
class CodingCheckpointProjection:
    checkpoint_id: str
    run_id: str
    seq: int
    loop_state: Mapping[str, Any]
    workspace_revision: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CodingWorkspaceProjection:
    revision: str
    git_head: str | None
    changed_files: tuple[str, ...]
    user_edits: tuple["CodingWorkspaceEditProjection", ...]


@dataclass(frozen=True, slots=True)
class CodingWorkspaceEditProjection:
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: str
    applied_checkpoint_id: str | None


@dataclass(frozen=True, slots=True)
class CodingProjectionSnapshot:
    task: CodingTaskProjection
    active_run: CodingRunProjection | None
    phases: tuple[CodingPhaseProjection, ...]
    tools: tuple[CodingToolProjection, ...]
    approvals: tuple[CodingApprovalProjection, ...]
    parts: tuple[CodingTextPartProjection, ...]
    todos: tuple[Mapping[str, Any], ...]
    workspace: CodingWorkspaceProjection
    latest_checkpoint: CodingCheckpointProjection | None
    head_seq: int
    connection_basis: str = "checkpoint"


class ProjectionRepository(Protocol):
    async def get_owned_snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingProjectionRows | None: ...


class CodingSnapshotService:
    def __init__(self, repository: ProjectionRepository) -> None:
        self._repository = repository

    async def get_owned(
        self, task_id: str, owner_id: str
    ) -> CodingProjectionSnapshot | None:
        rows = await self._repository.get_owned_snapshot(task_id, owner_id)
        if rows is None:
            return None
        runs = tuple(
            CodingRunProjection(
                run_id=row.run_id,
                attempt=row.attempt,
                status=row.status,
                resume_from_checkpoint_id=row.resume_from_checkpoint_id,
            )
            for row in rows.runs
        )
        active = next(
            (run for run in reversed(runs) if run.status == "running"), None
        )
        phases = tuple(
            CodingPhaseProjection(
                phase_id=row.phase_id,
                run_id=row.run_id,
                kind=CodingPhaseKind(row.kind),
                attempt=row.attempt,
                status=row.status,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in rows.phases
        )
        tools_rows = rows.tools
        approvals = tuple(
            CodingApprovalProjection(
                approval_id=row["approval_id"],
                tool_name=row["tool_name"],
                risk=ToolRisk(row["risk"]),
                status=ApprovalStatus(row["status"]),
                requested_at=row["requested_at"],
                expires_at=row["expires_at"],
                display_summary=dict(row["display_summary"]),
            )
            for row in rows.approvals
        )
        parts = tuple(
            CodingTextPartProjection(
                part_id=row.part_id,
                run_id=row.run_id,
                turn_id=row.turn_id,
                status=TextPartStatus(row.status),
                content=row.content,
                first_seq=row.first_seq,
                last_seq=row.last_seq,
            )
            for row in rows.parts
        )
        checkpoint = (
            CodingCheckpointProjection(
                checkpoint_id=rows.latest_checkpoint.checkpoint_id,
                run_id=rows.latest_checkpoint.run_id,
                seq=rows.latest_checkpoint.seq,
                loop_state=rows.latest_checkpoint.loop_state,
                workspace_revision=rows.latest_checkpoint.workspace_revision,
                created_at=rows.latest_checkpoint.created_at,
            )
            if rows.latest_checkpoint
            else None
        )
        loop_state = checkpoint.loop_state if checkpoint else {}
        tool_names = _tool_names(loop_state)
        tools = tuple(
            CodingToolProjection(
                tool_call_id=row.tool_call_id,
                run_id=row.run_id,
                status=row.status,
                result=row.result,
                name=tool_names.get(row.tool_call_id)
                or _name_from_result(row.result),
                preview=_preview_from_result(row.result),
            )
            for row in tools_rows
        )
        workspace = CodingWorkspaceProjection(
            revision=checkpoint.workspace_revision if checkpoint else "uninitialized",
            git_head=loop_state.get("git_head"),
            changed_files=tuple(loop_state.get("changed_files", [])),
            user_edits=tuple(
                CodingWorkspaceEditProjection(
                    edit_id=row.edit_id,
                    path=row.path,
                    base_revision=row.base_revision,
                    resulting_revision=row.resulting_revision,
                    status={
                        "committed": "pending_agent_sync",
                        "applied": "agent_synced",
                        "reconcile_required": "reconcile_required",
                    }[row.status],
                    applied_checkpoint_id=row.applied_checkpoint_id,
                )
                for row in rows.workspace_edits
            ),
        )
        return CodingProjectionSnapshot(
            task=CodingTaskProjection(
                task_id=rows.task.task_id,
                status=rows.task.status,
                version=rows.task.version,
                last_seq=rows.task.last_seq,
                created_at=rows.task.created_at,
                updated_at=rows.task.updated_at,
            ),
            active_run=active,
            phases=phases,
            tools=tools,
            approvals=approvals,
            parts=parts,
            todos=rows.todos,
            workspace=workspace,
            latest_checkpoint=checkpoint,
            head_seq=rows.head_seq,
        )


def _tool_names(loop_state: Mapping[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in loop_state.get("pending_tool_calls") or ():
        _remember_tool_name(names, item)
    for message in loop_state.get("transcript") or ():
        if not isinstance(message, Mapping):
            continue
        for item in message.get("content") or ():
            _remember_tool_name(names, item)
    return names


def _remember_tool_name(names: dict[str, str], item: object) -> None:
    if not isinstance(item, Mapping):
        return
    tool_call_id = item.get("tool_call_id")
    name = item.get("name")
    if isinstance(tool_call_id, str) and isinstance(name, str) and name:
        names[tool_call_id] = name


def _name_from_result(result: Mapping[str, Any] | None) -> str | None:
    if not isinstance(result, Mapping):
        return None
    for key in ("name", "tool_name", "tool"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _preview_from_result(result: Mapping[str, Any] | None) -> str | None:
    if not isinstance(result, Mapping):
        return None
    preview = result.get("preview")
    if isinstance(preview, str) and preview.strip():
        return preview.strip()[:200]
    return None
