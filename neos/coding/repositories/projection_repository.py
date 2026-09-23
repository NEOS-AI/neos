from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import bindparam, text

from neos.coding.persistence.postgres import SessionFactory


@dataclass(frozen=True, slots=True)
class CodingTaskRow:
    task_id: str
    status: str
    version: int
    last_seq: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CodingRunRow:
    run_id: str
    attempt: int
    status: str
    resume_from_checkpoint_id: str | None


@dataclass(frozen=True, slots=True)
class CodingPhaseRow:
    phase_id: str
    run_id: str
    kind: str
    attempt: int
    status: str
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CodingToolExecutionRow:
    tool_call_id: str
    run_id: str
    status: str
    result: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class CodingCheckpointRow:
    checkpoint_id: str
    run_id: str
    seq: int
    loop_state: Mapping[str, Any]
    workspace_revision: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CodingTextPartRow:
    part_id: str
    run_id: str
    turn_id: str
    status: str
    content: str
    first_seq: int
    last_seq: int


@dataclass(frozen=True, slots=True)
class CodingWorkspaceEditRow:
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: str
    applied_checkpoint_id: str | None


@dataclass(frozen=True, slots=True)
class CodingToolRiskRow:
    """The latest Jev verdict the ledger holds for one tool call.

    Read from `coding_events`, not from `coding_tool_executions`: the verdict
    is written *before* the tool runs, and a call parked on approval has no
    execution row at all. Joining on executions would lose exactly the calls
    the gate stopped.
    """

    tool_call_id: str
    kind: str
    seq: int
    payload: Mapping[str, Any]


#: Jev's event kinds (`neos.jev.gate`). Spelled here rather than imported so
#: the projection layer does not pull the Jev package in; the coding event-kind
#: fixture test fails if the two ever disagree.
TOOL_RISK_EVENT_TYPES = ("jev_risk_scored", "jev_unavailable")


@dataclass(frozen=True, slots=True)
class CodingProjectionRows:
    task: CodingTaskRow
    runs: tuple[CodingRunRow, ...]
    phases: tuple[CodingPhaseRow, ...]
    tools: tuple[CodingToolExecutionRow, ...]
    approvals: tuple[Mapping[str, Any], ...]
    parts: tuple[CodingTextPartRow, ...]
    workspace_edits: tuple[CodingWorkspaceEditRow, ...]
    todos: tuple[Mapping[str, Any], ...]
    latest_checkpoint: CodingCheckpointRow | None
    head_seq: int
    tool_risks: tuple[CodingToolRiskRow, ...] = ()


class PostgresCodingProjectionRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_owned_snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingProjectionRows | None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                )
                result = await session.execute(
                    text(
                        """
                        SELECT task_id, status, version, last_seq,
                               created_at, updated_at
                        FROM coding_tasks
                        WHERE task_id = :task_id
                          AND owner_id = :owner_id
                          AND deleted_at IS NULL
                        """
                    ),
                    {"task_id": task_id, "owner_id": owner_id},
                )
                task_record = result.first()
                if task_record is None:
                    return None
                runs = await self._runs(session, task_id)
                phases = await self._phases(session, task_id)
                tools = await self._tools(session, task_id)
                approvals = await self._approvals(session, task_id, owner_id)
                parts = await self._parts(session, task_id)
                workspace_edits = await self._workspace_edits(session, task_id)
                checkpoint = await self._checkpoint(session, task_id)
                tool_risks = await self._tool_risks(session, task_id)

        task = CodingTaskRow(
            task_id=task_record[0],
            status=task_record[1],
            version=int(task_record[2]),
            last_seq=int(task_record[3]),
            created_at=task_record[4],
            updated_at=task_record[5],
        )
        todos = tuple(
            dict(item)
            for item in (
                checkpoint.loop_state.get("todos", []) if checkpoint else []
            )
        )
        return CodingProjectionRows(
            task=task,
            runs=runs,
            phases=phases,
            tools=tools,
            approvals=approvals,
            parts=parts,
            workspace_edits=workspace_edits,
            todos=todos,
            latest_checkpoint=checkpoint,
            head_seq=task.last_seq,
            tool_risks=tool_risks,
        )

    async def _runs(self, session, task_id: str) -> tuple[CodingRunRow, ...]:
        result = await session.execute(
            text(
                """
                SELECT run_id, attempt, status, resume_from_checkpoint_id
                FROM coding_runs WHERE task_id = :task_id
                ORDER BY attempt ASC
                """
            ),
            {"task_id": task_id},
        )
        return tuple(
            CodingRunRow(row[0], int(row[1]), row[2], row[3])
            for row in result.all()
        )

    async def _phases(self, session, task_id: str) -> tuple[CodingPhaseRow, ...]:
        result = await session.execute(
            text(
                """
                SELECT phase_id, run_id, phase_kind, attempt, status,
                       started_at, completed_at
                FROM coding_phases WHERE task_id = :task_id
                ORDER BY started_at ASC, attempt ASC
                """
            ),
            {"task_id": task_id},
        )
        return tuple(
            CodingPhaseRow(row[0], row[1], row[2], int(row[3]), row[4], row[5], row[6])
            for row in result.all()
        )

    async def _tools(self, session, task_id: str) -> tuple[CodingToolExecutionRow, ...]:
        result = await session.execute(
            text(
                """
                SELECT tool_call_id, run_id, status, result_json
                FROM coding_tool_executions WHERE task_id = :task_id
                ORDER BY completed_at ASC NULLS LAST, tool_call_id ASC
                """
            ),
            {"task_id": task_id},
        )
        return tuple(
            CodingToolExecutionRow(
                row[0], row[1], row[2], dict(row[3]) if row[3] is not None else None
            )
            for row in result.all()
        )

    async def _tool_risks(
        self, session, task_id: str
    ) -> tuple[CodingToolRiskRow, ...]:
        # Latest verdict per call. A call is scored once today, but "latest"
        # keeps a re-score (a resumed run) from showing a stale band.
        result = await session.execute(
            text(
                """
                SELECT DISTINCT ON (tool_call_id)
                       tool_call_id, event_type, seq, payload
                FROM coding_events
                WHERE task_id = :task_id
                  AND tool_call_id IS NOT NULL
                  AND event_type IN :event_types
                ORDER BY tool_call_id, seq DESC
                """
            ).bindparams(bindparam("event_types", expanding=True)),
            {"task_id": task_id, "event_types": list(TOOL_RISK_EVENT_TYPES)},
        )
        return tuple(
            CodingToolRiskRow(
                tool_call_id=row[0],
                kind=row[1],
                seq=int(row[2]),
                payload=dict(row[3]) if row[3] is not None else {},
            )
            for row in result.all()
        )

    async def _approvals(
        self, session, task_id: str, owner_id: str
    ) -> tuple[Mapping[str, Any], ...]:
        result = await session.execute(
            text(
                """
                SELECT a.approval_id, a.tool_name, a.risk, a.status,
                       a.requested_at, a.expires_at, a.display_summary_json
                FROM coding_approvals a
                JOIN coding_tasks t ON t.task_id = a.task_id
                WHERE a.task_id = :task_id AND t.owner_id = :owner_id
                  AND t.deleted_at IS NULL
                ORDER BY requested_at ASC
                """
            ),
            {"task_id": task_id, "owner_id": owner_id},
        )
        return tuple(
            {
                "approval_id": row[0],
                "tool_name": row[1],
                "risk": row[2],
                "status": row[3],
                "requested_at": row[4],
                "expires_at": row[5],
                "display_summary": dict(row[6]),
            }
            for row in result.all()
        )

    async def _parts(self, session, task_id: str) -> tuple[CodingTextPartRow, ...]:
        result = await session.execute(
            text(
                """
                SELECT part_id, run_id, turn_id, status, content,
                       first_seq, last_seq
                FROM coding_text_parts
                WHERE task_id = :task_id
                ORDER BY first_seq ASC, part_id ASC
                """
            ),
            {"task_id": task_id},
        )
        return tuple(
            CodingTextPartRow(
                row[0], row[1], row[2], row[3], row[4], int(row[5]), int(row[6])
            )
            for row in result.all()
        )

    async def _workspace_edits(
        self, session, task_id: str
    ) -> tuple[CodingWorkspaceEditRow, ...]:
        result = await session.execute(
            text(
                """
                SELECT edit_id, path, base_revision, resulting_revision,
                       status, applied_checkpoint_id
                FROM (
                    SELECT edit_id, path, base_revision, resulting_revision,
                           status, applied_checkpoint_id, created_at
                    FROM coding_workspace_edits
                    WHERE task_id = :task_id
                      AND status IN (
                          'committed', 'reconcile_required', 'applied'
                      )
                    ORDER BY created_at DESC, edit_id DESC
                    LIMIT 100
                ) AS recent
                ORDER BY created_at, edit_id
                """
            ),
            {"task_id": task_id},
        )
        return tuple(
            CodingWorkspaceEditRow(
                edit_id=row[0],
                path=row[1],
                base_revision=row[2],
                resulting_revision=row[3],
                status=row[4],
                applied_checkpoint_id=row[5],
            )
            for row in result.all()
        )

    async def _checkpoint(
        self, session, task_id: str
    ) -> CodingCheckpointRow | None:
        result = await session.execute(
            text(
                """
                SELECT checkpoint_id, run_id, seq, loop_state_json,
                       workspace_revision, created_at
                FROM coding_checkpoints WHERE task_id = :task_id
                ORDER BY seq DESC LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
        row = result.first()
        if row is None:
            return None
        return CodingCheckpointRow(
            row[0], row[1], int(row[2]), dict(row[3]), row[4], row[5]
        )
