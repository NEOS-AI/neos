import json
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text

from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhase,
    CodingPhaseKind,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.persistence.postgres import SessionFactory


class PostgresCodingRunRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_run(self, run: CodingRun) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_runs
                            (run_id, task_id, attempt, status,
                             resume_from_checkpoint_id, started_at, completed_at)
                        VALUES
                            (:run_id, :task_id, :attempt, :status,
                             :resume_from_checkpoint_id, :started_at, :completed_at)
                        ON CONFLICT (run_id) DO NOTHING
                        """
                    ),
                    {
                        "run_id": run.run_id,
                        "task_id": run.task_id,
                        "attempt": run.attempt,
                        "status": run.status.value,
                        "resume_from_checkpoint_id": run.resume_from_checkpoint_id,
                        "started_at": run.started_at,
                        "completed_at": run.completed_at,
                    },
                )

    async def latest_run(self, task_id: str) -> CodingRun | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT run_id, task_id, attempt, status,
                           resume_from_checkpoint_id, started_at, completed_at
                    FROM coding_runs
                    WHERE task_id = :task_id
                    ORDER BY attempt DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
            row = result.first()
        if row is None:
            return None
        return CodingRun(
            run_id=row[0],
            task_id=row[1],
            attempt=int(row[2]),
            status=CodingRunStatus(row[3]),
            resume_from_checkpoint_id=row[4],
            started_at=row[5],
            completed_at=row[6],
        )

    async def update_run(self, run: CodingRun) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE coding_runs
                        SET status = :status,
                            completed_at = :completed_at
                        WHERE run_id = :run_id
                        """
                    ),
                    {
                        "run_id": run.run_id,
                        "status": run.status.value,
                        "completed_at": run.completed_at,
                    },
                )

    async def save_checkpoint(self, checkpoint: CodingCheckpoint) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:state AS JSONB), :workspace_revision, :created_at)
                        ON CONFLICT (checkpoint_id) DO NOTHING
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "task_id": checkpoint.task_id,
                        "run_id": checkpoint.run_id,
                        "seq": checkpoint.seq,
                        "state": json.dumps(dict(checkpoint.loop_state)),
                        "workspace_revision": checkpoint.workspace_revision,
                        "created_at": checkpoint.created_at,
                    },
                )

    async def phase_history(
        self, task_id: str
    ) -> tuple[tuple[CodingPhaseKind, int], ...]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT phase_kind, attempt FROM coding_phases
                    WHERE task_id = :task_id
                    ORDER BY started_at, attempt
                    """
                ),
                {"task_id": task_id},
            )
            rows = result.all()
        return tuple((CodingPhaseKind(row[0]), int(row[1])) for row in rows)

    async def save_phase(self, phase: CodingPhase) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_phases
                            (phase_id, task_id, run_id, phase_kind, attempt,
                             status, started_at, completed_at)
                        VALUES
                            (:phase_id, :task_id, :run_id, :phase_kind, :attempt,
                             :status, :started_at, :completed_at)
                        ON CONFLICT (phase_id) DO UPDATE
                        SET status = EXCLUDED.status,
                            completed_at = EXCLUDED.completed_at
                        """
                    ),
                    {
                        "phase_id": phase.phase_id,
                        "task_id": phase.task_id,
                        "run_id": phase.run_id,
                        "phase_kind": phase.kind.value,
                        "attempt": phase.attempt,
                        "status": phase.status.value,
                        "started_at": phase.started_at,
                        "completed_at": phase.completed_at,
                    },
                )

    async def latest_checkpoint(self, task_id: str) -> CodingCheckpoint | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT checkpoint_id, task_id, run_id, seq,
                           loop_state_json, workspace_revision, created_at
                    FROM coding_checkpoints
                    WHERE task_id = :task_id
                    ORDER BY seq DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
            row = result.first()
        if row is None:
            return None
        return CodingCheckpoint(
            checkpoint_id=row[0],
            task_id=row[1],
            run_id=row[2],
            seq=int(row[3]),
            loop_state=dict(row[4]),
            workspace_revision=row[5],
            created_at=row[6],
        )

    async def completed_tool_result(
        self, task_id: str, tool_call_id: str
    ) -> Mapping[str, Any] | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT result_json
                    FROM coding_tool_executions
                    WHERE task_id = :task_id
                      AND tool_call_id = :tool_call_id
                      AND status = 'completed'
                    """
                ),
                {"task_id": task_id, "tool_call_id": tool_call_id},
            )
            row = result.first()
        return dict(row[0]) if row is not None else None

    async def record_tool_result(
        self,
        *,
        task_id: str,
        run_id: str,
        tool_call_id: str,
        result: Mapping[str, Any],
        completed_at: datetime,
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_tool_executions
                            (task_id, tool_call_id, run_id, status,
                             result_json, completed_at)
                        VALUES
                            (:task_id, :tool_call_id, :run_id, 'completed',
                             CAST(:result AS JSONB), :completed_at)
                        ON CONFLICT (task_id, tool_call_id) DO NOTHING
                        """
                    ),
                    {
                        "task_id": task_id,
                        "tool_call_id": tool_call_id,
                        "run_id": run_id,
                        "result": json.dumps(dict(result)),
                        "completed_at": completed_at,
                    },
                )

    async def queue_steering(self, request: SteeringRequest) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_steering_requests
                            (steering_id, task_id, mode, instruction,
                             status, requested_at, applied_checkpoint_id)
                        VALUES
                            (:steering_id, :task_id, :mode, :instruction,
                             'pending', :requested_at, :applied_checkpoint_id)
                        ON CONFLICT (steering_id) DO NOTHING
                        """
                    ),
                    {
                        "steering_id": request.steering_id,
                        "task_id": request.task_id,
                        "mode": request.mode.value,
                        "instruction": request.instruction,
                        "requested_at": request.requested_at,
                        "applied_checkpoint_id": request.applied_checkpoint_id,
                    },
                )

    async def claim_pending_steering(
        self, task_id: str
    ) -> SteeringRequest | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH pending AS (
                            SELECT steering_id
                            FROM coding_steering_requests
                            WHERE task_id = :task_id AND status = 'pending'
                            ORDER BY requested_at, steering_id
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE coding_steering_requests request
                        SET status = 'claimed'
                        FROM pending
                        WHERE request.steering_id = pending.steering_id
                        RETURNING request.steering_id, request.task_id,
                                  request.mode, request.instruction,
                                  request.requested_at
                        """
                    ),
                    {"task_id": task_id},
                )
                row = result.first()
        if row is None:
            return None
        return SteeringRequest(
            steering_id=row[0],
            task_id=row[1],
            mode=SteeringMode(row[2]),
            instruction=row[3],
            requested_at=row[4],
        )

    async def apply_steering(self, request: SteeringRequest) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE coding_steering_requests
                        SET status = 'applied',
                            applied_checkpoint_id = :checkpoint_id
                        WHERE steering_id = :steering_id
                          AND status = 'claimed'
                        """
                    ),
                    {
                        "steering_id": request.steering_id,
                        "checkpoint_id": request.applied_checkpoint_id,
                    },
                )
