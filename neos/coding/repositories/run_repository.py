import json
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text

from neos.coding.domain.durability import (
    ExecutionLease,
    StaleExecutionLease,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.events import CodingEvent
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
    def __init__(
        self,
        session_factory: SessionFactory,
        wake_outbox=None,
    ) -> None:
        self._session_factory = session_factory
        self._wake_outbox = wake_outbox

    async def acquire_execution_lease(
        self,
        *,
        task_id: str,
        run_id: str,
        worker_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionLease | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO coding_run_leases
                            (task_id, run_id, worker_id, fencing_token,
                             acquired_at, heartbeat_at, expires_at)
                        VALUES
                            (:task_id, :run_id, :worker_id, 1,
                             :now, :now, :expires_at)
                        ON CONFLICT (task_id) DO UPDATE
                        SET run_id = EXCLUDED.run_id,
                            worker_id = EXCLUDED.worker_id,
                            fencing_token =
                                coding_run_leases.fencing_token + 1,
                            acquired_at = EXCLUDED.acquired_at,
                            heartbeat_at = EXCLUDED.heartbeat_at,
                            expires_at = EXCLUDED.expires_at
                        WHERE coding_run_leases.expires_at <= :now
                        RETURNING task_id, run_id, worker_id, fencing_token,
                                  acquired_at, expires_at,
                                  fencing_token > 1 AS recovered
                        """
                    ),
                    {
                        "task_id": task_id,
                        "run_id": run_id,
                        "worker_id": worker_id,
                        "now": now,
                        "expires_at": expires_at,
                    },
                )
                row = result.first()
        return self._lease_from_row(row) if row is not None else None

    async def renew_execution_lease(
        self,
        lease: ExecutionLease,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionLease:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        UPDATE coding_run_leases
                        SET heartbeat_at = :now,
                            expires_at = :expires_at
                        WHERE task_id = :task_id
                          AND run_id = :run_id
                          AND worker_id = :worker_id
                          AND fencing_token = :fencing_token
                          AND expires_at > :now
                        RETURNING task_id, run_id, worker_id, fencing_token,
                                  acquired_at, expires_at, FALSE AS recovered
                        """
                    ),
                    self._lease_params(
                        lease, now=now, expires_at=expires_at
                    ),
                )
                row = result.first()
        if row is None:
            raise StaleExecutionLease(lease.task_id)
        return self._lease_from_row(row)

    async def release_execution_lease(
        self, lease: ExecutionLease, *, now: datetime
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        UPDATE coding_run_leases
                        SET expires_at = :now,
                            heartbeat_at = :now
                        WHERE task_id = :task_id
                          AND run_id = :run_id
                          AND worker_id = :worker_id
                          AND fencing_token = :fencing_token
                        RETURNING task_id
                        """
                    ),
                    self._lease_params(lease, now=now),
                )
                row = result.first()
        if row is None:
            raise StaleExecutionLease(lease.task_id)

    async def claim_tool_execution(
        self,
        *,
        lease: ExecutionLease,
        tool_call_id: str,
        now: datetime,
        claim_expires_at: datetime,
    ) -> ToolExecutionClaim:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH valid_lease AS (
                            SELECT 1
                            FROM coding_run_leases
                            WHERE task_id = :task_id
                              AND run_id = :run_id
                              AND worker_id = :worker_id
                              AND fencing_token = :fencing_token
                              AND expires_at > :now
                        ), claimed AS (
                            INSERT INTO coding_tool_executions
                                (task_id, tool_call_id, run_id, status,
                                 worker_id, fencing_token, claimed_at,
                                 claim_expires_at)
                            SELECT :task_id, :tool_call_id, :run_id, 'claimed',
                                   :worker_id, :fencing_token, :now,
                                   :claim_expires_at
                            FROM valid_lease
                            ON CONFLICT (task_id, tool_call_id) DO UPDATE
                            SET run_id = EXCLUDED.run_id,
                                status = 'claimed',
                                worker_id = EXCLUDED.worker_id,
                                fencing_token = EXCLUDED.fencing_token,
                                claimed_at = EXCLUDED.claimed_at,
                                claim_expires_at = EXCLUDED.claim_expires_at
                            WHERE coding_tool_executions.status != 'completed'
                              AND coding_tool_executions.claim_expires_at <= :now
                            RETURNING status, result_json
                        )
                        SELECT status, result_json, TRUE AS lease_valid
                        FROM claimed
                        UNION ALL
                        SELECT execution.status, execution.result_json,
                               TRUE AS lease_valid
                        FROM coding_tool_executions execution, valid_lease
                        WHERE execution.task_id = :task_id
                          AND execution.tool_call_id = :tool_call_id
                          AND execution.status = 'completed'
                          AND NOT EXISTS (SELECT 1 FROM claimed)
                        UNION ALL
                        SELECT NULL, NULL, FALSE AS lease_valid
                        WHERE NOT EXISTS (SELECT 1 FROM valid_lease)
                        LIMIT 1
                        """
                    ),
                    {
                        **self._lease_params(lease, now=now),
                        "tool_call_id": tool_call_id,
                        "claim_expires_at": claim_expires_at,
                    },
                )
                row = result.first()
        if row is not None and len(row) > 2 and not row[2]:
            raise StaleExecutionLease(lease.task_id)
        if row is None:
            disposition = ToolExecutionDisposition.BUSY
            persisted = None
        else:
            disposition = ToolExecutionDisposition(row[0])
            persisted = dict(row[1]) if row[1] is not None else None
        return ToolExecutionClaim(
            disposition=disposition,
            tool_call_id=tool_call_id,
            lease=lease,
            result=persisted,
        )

    async def complete_tool_execution(
        self,
        claim: ToolExecutionClaim,
        *,
        result: Mapping[str, Any],
        now: datetime,
    ) -> CodingEvent:
        if claim.disposition is not ToolExecutionDisposition.CLAIMED:
            raise ValueError("only a claimed tool execution can complete")
        lease = claim.lease
        async with await self._session_factory() as session:
            async with session.begin():
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_tool_executions execution
                        SET status = 'completed',
                            result_json = CAST(:result AS JSONB),
                            completed_at = :now
                        FROM coding_run_leases lease
                        WHERE execution.task_id = :task_id
                          AND execution.tool_call_id = :tool_call_id
                          AND execution.status = 'claimed'
                          AND execution.worker_id = :worker_id
                          AND execution.fencing_token = :fencing_token
                          AND lease.task_id = execution.task_id
                          AND lease.run_id = :run_id
                          AND lease.worker_id = :worker_id
                          AND lease.fencing_token = :fencing_token
                          AND lease.expires_at > :now
                        RETURNING execution.task_id
                        """
                    ),
                    {
                        **self._lease_params(lease, now=now),
                        "tool_call_id": claim.tool_call_id,
                        "result": json.dumps(dict(result)),
                    },
                )
                if updated.first() is None:
                    raise StaleExecutionLease(lease.task_id)
                event = await self._append_event_in_session(
                    session,
                    task_id=lease.task_id,
                    event_type="tool.completed",
                    payload={"result": dict(result), "reused": False},
                    now=now,
                    run_id=lease.run_id,
                    tool_call_id=claim.tool_call_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return event

    @staticmethod
    def _lease_from_row(row) -> ExecutionLease:
        return ExecutionLease(
            task_id=row[0],
            run_id=row[1],
            worker_id=row[2],
            fencing_token=int(row[3]),
            acquired_at=row[4],
            expires_at=row[5],
            recovered=bool(row[6]),
        )

    @staticmethod
    def _lease_params(
        lease: ExecutionLease, **extra
    ) -> dict[str, Any]:
        return {
            "task_id": lease.task_id,
            "run_id": lease.run_id,
            "worker_id": lease.worker_id,
            "fencing_token": lease.fencing_token,
            **extra,
        }

    async def _append_event_in_session(
        self,
        session,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        run_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> CodingEvent:
        sequence = await session.execute(
            text(
                """
                UPDATE coding_tasks
                SET last_seq = last_seq + 1,
                    updated_at = :now,
                    last_activity_at = :now
                WHERE task_id = :task_id
                RETURNING last_seq
                """
            ),
            {"task_id": task_id, "now": now},
        )
        row = sequence.first()
        if row is None:
            raise RuntimeError(f"coding task does not exist: {task_id}")
        event = CodingEvent(
            version=1,
            task_id=task_id,
            seq=int(row[0]),
            event_id=f"ce_{uuid4().hex}",
            type=event_type,
            payload=dict(payload),
            created_at=now,
            run_id=run_id,
            tool_call_id=tool_call_id,
            checkpoint_id=checkpoint_id,
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_events
                    (event_id, task_id, seq, version, event_type, payload,
                     created_at, run_id, turn_id, tool_call_id, checkpoint_id)
                VALUES
                    (:event_id, :task_id, :seq, 1, :event_type,
                     CAST(:payload AS JSONB), :created_at,
                     :run_id, NULL, :tool_call_id, :checkpoint_id)
                """
            ),
            {
                "event_id": event.event_id,
                "task_id": task_id,
                "seq": event.seq,
                "event_type": event_type,
                "payload": json.dumps(dict(payload)),
                "created_at": now,
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "checkpoint_id": checkpoint_id,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_event_outbox
                    (outbox_id, event_id, task_id, seq,
                     next_attempt_at, created_at)
                VALUES
                    (:outbox_id, :event_id, :task_id, :seq, :now, :now)
                ON CONFLICT (event_id) DO NOTHING
                """
            ),
            {
                "outbox_id": f"co_{uuid4().hex}",
                "event_id": event.event_id,
                "task_id": task_id,
                "seq": event.seq,
                "now": now,
            },
        )
        return event

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
