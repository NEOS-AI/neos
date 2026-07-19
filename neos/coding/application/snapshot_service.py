from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from neos.coding.domain.phases import CodingPhaseKind
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


@dataclass(frozen=True, slots=True)
class CodingProjectionSnapshot:
    task: CodingTaskProjection
    active_run: CodingRunProjection | None
    phases: tuple[CodingPhaseProjection, ...]
    tools: tuple[CodingToolProjection, ...]
    approvals: tuple[Mapping[str, Any], ...]
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
        tools = tuple(
            CodingToolProjection(
                tool_call_id=row.tool_call_id,
                run_id=row.run_id,
                status=row.status,
                result=row.result,
            )
            for row in rows.tools
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
        workspace = CodingWorkspaceProjection(
            revision=checkpoint.workspace_revision if checkpoint else "uninitialized",
            git_head=loop_state.get("git_head"),
            changed_files=tuple(loop_state.get("changed_files", [])),
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
            approvals=rows.approvals,
            todos=rows.todos,
            workspace=workspace,
            latest_checkpoint=checkpoint,
            head_seq=rows.head_seq,
        )
