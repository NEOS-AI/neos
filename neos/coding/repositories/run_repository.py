import json
from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text

from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalNotFound,
    ApprovalRequestCommit,
    ApprovalResolutionCommit,
    ApprovalStatus,
    CodingApproval,
    approval_display_summary,
    canonical_approval_hash,
)
from neos.coding.domain.durability import (
    ExecutionLease,
    ModelCheckpointCommit,
    PhaseCheckpointCommit,
    PhaseStart,
    RunLifecycleCommit,
    StaleExecutionLease,
    SteeringApplication,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.text_parts import (
    CodingTextPart,
    ModelTextPartCommit,
    TextPartConflict,
    TextPartStatus,
)
from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditApplication,
    WorkspaceEditStatus,
)
from neos.coding.loop.base import EXPECTED_CHECKPOINT_OMITTED

from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhase,
    CodingPhaseKind,
    CodingPhaseStatus,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.persistence.postgres import SessionFactory
from neos.coding.model.base import ToolCallCompleted
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall


class PostgresCodingRunRepository:
    def __init__(
        self,
        session_factory: SessionFactory,
        wake_outbox=None,
    ) -> None:
        self._session_factory = session_factory
        self._wake_outbox = wake_outbox

    async def ensure_run_started(
        self,
        *,
        task_id: str,
        instruction: str,
        development_mode: bool,
        now: datetime,
    ) -> CodingRun:
        async with await self._session_factory() as session:
            async with session.begin():
                task_result = await session.execute(
                    text(
                        """
                        SELECT task_id, prompt, status
                        FROM coding_tasks
                        WHERE task_id = :task_id AND deleted_at IS NULL
                        FOR UPDATE
                        """
                    ),
                    {"task_id": task_id},
                )
                task_row = task_result.first()
                if task_row is None:
                    raise RuntimeError(f"coding task does not exist: {task_id}")
                existing_result = await session.execute(
                    text(
                        """
                        SELECT run_id, task_id, attempt, status,
                               resume_from_checkpoint_id, started_at, completed_at
                        FROM coding_runs
                        WHERE task_id = :task_id AND status = 'running'
                        ORDER BY attempt DESC
                        LIMIT 1
                        """
                    ),
                    {"task_id": task_id},
                )
                existing_row = existing_result.first()
                if existing_row is not None:
                    return self._run_from_row(existing_row)
                if task_row[2] in {"completed", "failed", "cancelled"}:
                    terminal_result = await session.execute(
                        text(
                            """
                            SELECT run_id, task_id, attempt, status,
                                   resume_from_checkpoint_id, started_at,
                                   completed_at
                            FROM coding_runs
                            WHERE task_id = :task_id
                            ORDER BY attempt DESC
                            LIMIT 1
                            """
                        ),
                        {"task_id": task_id},
                    )
                    terminal_row = terminal_result.first()
                    if terminal_row is None:
                        raise RuntimeError(
                            f"terminal coding task has no run: {task_id}"
                        )
                    return self._run_from_row(terminal_row)
                if task_row[2] == "queued" and not development_mode:
                    raise ValueError("queued task fast path requires development mode")
                attempt_result = await session.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(attempt), 0)
                        FROM coding_runs
                        WHERE task_id = :task_id
                        """
                    ),
                    {"task_id": task_id},
                )
                attempt = int(attempt_result.first()[0]) + 1
                run = CodingRun(
                    run_id=f"cr_{uuid4().hex}",
                    task_id=task_id,
                    attempt=attempt,
                    status=CodingRunStatus.RUNNING,
                    resume_from_checkpoint_id=None,
                    started_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_runs
                            (run_id, task_id, attempt, status,
                             resume_from_checkpoint_id, started_at, completed_at)
                        VALUES
                            (:run_id, :task_id, :attempt, 'running',
                             NULL, :now, NULL)
                        """
                    ),
                    {
                        "run_id": run.run_id,
                        "task_id": task_id,
                        "attempt": attempt,
                        "now": now,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_tasks
                        SET status = 'running', updated_at = :now
                        WHERE task_id = :task_id
                        """
                    ),
                    {"task_id": task_id, "now": now},
                )
                await self._append_event_in_session(
                    session,
                    task_id=task_id,
                    event_type="run.started",
                    payload={"instruction": instruction, "attempt": attempt},
                    now=now,
                    run_id=run.run_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return run

    async def complete_run(
        self, *, lease: ExecutionLease, now: datetime
    ) -> RunLifecycleCommit:
        return await self._commit_terminal_run(
            lease=lease,
            status=CodingRunStatus.COMPLETED,
            payload={"status": "completed"},
            now=now,
        )

    async def fail_run(
        self,
        *,
        lease: ExecutionLease,
        error_code: str,
        now: datetime,
    ) -> RunLifecycleCommit:
        if not error_code or not error_code.replace("_", "").isalnum():
            raise ValueError("error_code must be normalized")
        return await self._commit_terminal_run(
            lease=lease,
            status=CodingRunStatus.FAILED,
            payload={"status": "failed", "error_code": error_code},
            now=now,
        )

    async def _commit_terminal_run(
        self,
        *,
        lease: ExecutionLease,
        status: CodingRunStatus,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> RunLifecycleCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                run_result = await session.execute(
                    text(
                        """
                        SELECT run_id, task_id, attempt, status,
                               resume_from_checkpoint_id, started_at, completed_at
                        FROM coding_runs
                        WHERE run_id = :run_id AND task_id = :task_id
                        FOR UPDATE
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id},
                )
                run_row = run_result.first()
                if run_row is None:
                    raise StaleExecutionLease(lease.task_id)
                run = replace(
                    self._run_from_row(run_row),
                    status=status,
                    completed_at=now,
                )
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type=f"run.{status.value}",
                    payload=payload,
                    now=now,
                    run_id=lease.run_id,
                )
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_runs
                        SET status = :status, completed_at = :now
                        WHERE run_id = :run_id
                          AND task_id = :task_id
                          AND status = 'running'
                        RETURNING run_id
                        """
                    ),
                    {
                        "run_id": lease.run_id,
                        "task_id": lease.task_id,
                        "status": status.value,
                        "now": now,
                    },
                )
                if updated.first() is None:
                    raise StaleExecutionLease(lease.task_id)
                await session.execute(
                    text(
                        """
                        UPDATE coding_tasks
                        SET status = :status, updated_at = :now
                        WHERE task_id = :task_id
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "status": status.value,
                        "now": now,
                    },
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return RunLifecycleCommit(run=run, event=event)

    async def claimable_task_ids(self, *, limit: int) -> tuple[str, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT task.task_id
                    FROM coding_tasks task
                    WHERE task.deleted_at IS NULL
                      AND task.status IN ('queued', 'running')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM coding_runs run
                          WHERE run.task_id = task.task_id
                            AND run.status IN (
                                'completed', 'cancelled', 'failed'
                            )
                      )
                    ORDER BY task.last_activity_at, task.task_id
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            rows = result.all()
        return tuple(row[0] for row in rows)

    async def claimable_delivery_tokens(
        self, *, limit: int
    ) -> tuple[tuple[str, str | None], ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT task.task_id, durable_checkpoint.checkpoint_id
                    FROM coding_tasks task
                    JOIN LATERAL (
                        SELECT candidate.run_id, candidate.status
                        FROM coding_runs candidate
                        WHERE candidate.task_id = task.task_id
                        ORDER BY candidate.attempt DESC,
                                 candidate.started_at DESC,
                                 candidate.run_id DESC
                        LIMIT 1
                    ) canonical ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT checkpoint.checkpoint_id
                        FROM coding_checkpoints checkpoint
                        WHERE checkpoint.task_id = task.task_id
                          AND checkpoint.run_id = canonical.run_id
                        ORDER BY checkpoint.seq DESC
                        LIMIT 1
                    ) durable_checkpoint ON TRUE
                    WHERE task.deleted_at IS NULL
                      AND task.status IN ('queued', 'running')
                      AND canonical.status = 'running'
                    ORDER BY task.last_activity_at, task.task_id
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            rows = result.all()
        return tuple((row[0], row[1]) for row in rows)

    async def acquire_execution_lease(
        self,
        *,
        task_id: str,
        run_id: str,
        worker_id: str,
        now: datetime,
        expires_at: datetime,
        expected_checkpoint_id: str | None | object = EXPECTED_CHECKPOINT_OMITTED,
    ) -> ExecutionLease | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH previous AS (
                            SELECT worker_id
                            FROM coding_run_leases
                            WHERE task_id = :task_id
                            FOR UPDATE
                        ), canonical AS (
                            SELECT candidate.run_id, candidate.status
                            FROM coding_runs candidate
                            WHERE candidate.task_id = :task_id
                            ORDER BY candidate.attempt DESC,
                                     candidate.started_at DESC,
                                     candidate.run_id DESC
                            LIMIT 1
                        ), checkpoint_matches AS (
                            SELECT 1
                            WHERE (:validate_checkpoint = FALSE OR
                                   (SELECT checkpoint_id
                                   FROM coding_checkpoints
                                   WHERE task_id = :task_id
                                     AND run_id = :run_id
                                   ORDER BY seq DESC
                                   LIMIT 1)
                                  IS NOT DISTINCT FROM :expected_checkpoint_id)
                              AND EXISTS (
                                  SELECT 1 FROM canonical
                                  WHERE canonical.run_id = :run_id
                                    AND canonical.status = 'running'
                              )
                        ), acquired AS (
                            INSERT INTO coding_run_leases
                                (task_id, run_id, worker_id, fencing_token,
                                 acquired_at, heartbeat_at, expires_at)
                            SELECT :task_id, :run_id, :worker_id, 1,
                                   :now, :now, :expires_at
                            FROM checkpoint_matches
                            ON CONFLICT (task_id) DO UPDATE
                            SET run_id = EXCLUDED.run_id,
                                worker_id = EXCLUDED.worker_id,
                                fencing_token =
                                    coding_run_leases.fencing_token + 1,
                                acquired_at = EXCLUDED.acquired_at,
                                heartbeat_at = EXCLUDED.heartbeat_at,
                                expires_at = EXCLUDED.expires_at
                            WHERE coding_run_leases.expires_at <= :now
                            RETURNING task_id, run_id, worker_id,
                                      fencing_token, acquired_at, expires_at
                        )
                            SELECT task_id, run_id, worker_id, fencing_token,
                               acquired_at, expires_at,
                               COALESCE(
                                   (SELECT previous.worker_id <> :worker_id
                                    FROM previous),
                                   FALSE
                               ) AS recovered
                            FROM acquired
                        """
                    ),
                    {
                        "task_id": task_id,
                        "run_id": run_id,
                        "worker_id": worker_id,
                        "now": now,
                        "expires_at": expires_at,
                        "expected_checkpoint_id": (
                            None
                            if expected_checkpoint_id is EXPECTED_CHECKPOINT_OMITTED
                            else expected_checkpoint_id
                        ),
                        "validate_checkpoint": (
                            expected_checkpoint_id is not EXPECTED_CHECKPOINT_OMITTED
                        ),
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
                    self._lease_params(lease, now=now, expires_at=expires_at),
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
                        WITH prior_execution AS MATERIALIZED (
                            SELECT status
                            FROM coding_tool_executions
                            WHERE task_id = :task_id
                              AND tool_call_id = :tool_call_id
                        ), valid_lease AS (
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
                        SELECT CASE
                                   WHEN EXISTS (
                                       SELECT 1 FROM prior_execution
                                   ) THEN 'reclaimed'
                                   ELSE status
                               END AS disposition,
                               result_json, TRUE AS lease_valid
                        FROM claimed
                        UNION ALL
                        SELECT execution.status AS disposition,
                               execution.result_json,
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
        if claim.disposition not in {
            ToolExecutionDisposition.CLAIMED,
            ToolExecutionDisposition.RECLAIMED,
        }:
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

    async def request_tool_approval(
        self,
        *,
        lease: ExecutionLease,
        tool_call: ToolCallCompleted,
        validated: ValidatedToolCall,
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ApprovalRequestCommit:
        if expires_at <= requested_at:
            raise ValueError("approval expiry must follow request time")
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(
                    session, lease, now=requested_at
                )
                owner_result = await session.execute(
                    text(
                        """
                        SELECT task.owner_id
                        FROM coding_tasks task
                        JOIN coding_runs run
                          ON run.task_id = task.task_id
                        WHERE task.task_id = :task_id
                          AND task.deleted_at IS NULL
                          AND task.status = 'running'
                          AND run.run_id = :run_id
                          AND run.status = 'running'
                        FOR UPDATE OF task, run
                        """
                    ),
                    {"task_id": lease.task_id, "run_id": lease.run_id},
                )
                owner_row = owner_result.first()
                if owner_row is None:
                    raise StaleExecutionLease(lease.task_id)
                existing_result = await session.execute(
                    text(
                        """
                        SELECT approval.approval_id, approval.task_id,
                               approval.run_id, approval.tool_call_id,
                               approval.checkpoint_id, approval.tool_name,
                               approval.risk, approval.workspace_revision,
                               approval.request_hash, approval.display_summary,
                               approval.status, approval.requested_by,
                               approval.requested_at, approval.expires_at,
                               approval.decision, approval.decided_by,
                               approval.decided_at, checkpoint.seq,
                               checkpoint.loop_state_json,
                               checkpoint.created_at
                        FROM coding_approvals approval
                        JOIN coding_checkpoints checkpoint
                          ON checkpoint.checkpoint_id = approval.checkpoint_id
                        WHERE approval.task_id = :task_id
                          AND approval.run_id = :run_id
                          AND approval.tool_call_id = :tool_call_id
                        FOR UPDATE OF approval
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                )
                existing_row = existing_result.first()
                if existing_row is not None:
                    approval = self._approval_from_row(existing_row)
                    expected_hash = canonical_approval_hash(
                        self._approval_binding(
                            lease=lease,
                            tool_call=tool_call,
                            validated=validated,
                            checkpoint_id=approval.checkpoint_id,
                            workspace_revision=workspace_revision,
                        )
                    )
                    if (
                        approval.request_hash != expected_hash
                        or approval.workspace_revision != workspace_revision
                    ):
                        raise ApprovalConflict("approval_request_mismatch")
                    checkpoint = CodingCheckpoint(
                        checkpoint_id=approval.checkpoint_id,
                        task_id=lease.task_id,
                        run_id=lease.run_id,
                        seq=int(existing_row[17]),
                        loop_state=dict(existing_row[18]),
                        workspace_revision=approval.workspace_revision,
                        created_at=existing_row[19],
                    )
                    return ApprovalRequestCommit(
                        approval=approval,
                        checkpoint=checkpoint,
                        events=(),
                        created=False,
                    )
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=requested_at
                )
                checkpoint = CodingCheckpoint(
                    checkpoint_id=f"cc_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=seq,
                    loop_state=dict(loop_state),
                    workspace_revision=workspace_revision,
                    created_at=requested_at,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "seq": seq,
                        "loop_state": json.dumps(dict(loop_state)),
                        "workspace_revision": workspace_revision,
                        "created_at": requested_at,
                    },
                )
                request_hash = canonical_approval_hash(
                    self._approval_binding(
                        lease=lease,
                        tool_call=tool_call,
                        validated=validated,
                        checkpoint_id=checkpoint.checkpoint_id,
                        workspace_revision=workspace_revision,
                    )
                )
                summary = approval_display_summary(validated)
                approval = CodingApproval(
                    approval_id=f"ca_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    tool_call_id=tool_call.tool_call_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                    tool_name=validated.name,
                    risk=validated.risk,
                    workspace_revision=workspace_revision,
                    request_hash=request_hash,
                    display_summary=summary,
                    status=ApprovalStatus.PENDING,
                    requested_by=str(owner_row[0]),
                    requested_at=requested_at,
                    expires_at=expires_at,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_approvals
                            (approval_id, task_id, run_id, tool_call_id,
                             checkpoint_id, tool_name, risk,
                             workspace_revision, request_hash,
                             display_summary, status, requested_by,
                             requested_at, expires_at, decision,
                             decided_by, decided_at)
                        VALUES
                            (:approval_id, :task_id, :run_id, :tool_call_id,
                             :checkpoint_id, :tool_name, :risk,
                             :workspace_revision, :request_hash,
                             CAST(:display_summary AS JSONB), 'pending',
                             :requested_by, :requested_at, :expires_at,
                             NULL, NULL, NULL)
                        """
                    ),
                    {
                        "approval_id": approval.approval_id,
                        "task_id": approval.task_id,
                        "run_id": approval.run_id,
                        "tool_call_id": approval.tool_call_id,
                        "checkpoint_id": approval.checkpoint_id,
                        "tool_name": approval.tool_name,
                        "risk": approval.risk.value,
                        "workspace_revision": approval.workspace_revision,
                        "request_hash": approval.request_hash,
                        "display_summary": json.dumps(dict(summary)),
                        "requested_by": approval.requested_by,
                        "requested_at": requested_at,
                        "expires_at": expires_at,
                    },
                )
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_tasks
                        SET status = 'waiting_approval', updated_at = :now,
                            last_activity_at = :now
                        WHERE task_id = :task_id AND status = 'running'
                        RETURNING task_id
                        """
                    ),
                    {"task_id": lease.task_id, "now": requested_at},
                )
                if updated.first() is None:
                    raise StaleExecutionLease(lease.task_id)
                requested_event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="approval.requested",
                    payload=self._approval_event_payload(approval),
                    now=requested_at,
                    run_id=lease.run_id,
                    tool_call_id=tool_call.tool_call_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                )
                status_event = await self._append_event_in_session(
                    session,
                    task_id=lease.task_id,
                    event_type="task.status.changed",
                    payload={"status": "waiting_approval"},
                    now=requested_at,
                    run_id=lease.run_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ApprovalRequestCommit(
            approval=approval,
            checkpoint=checkpoint,
            events=(requested_event, status_event),
            created=True,
        )

    async def get_tool_approval(
        self, *, task_id: str, run_id: str, tool_call_id: str
    ) -> CodingApproval | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT approval_id, task_id, run_id, tool_call_id,
                           checkpoint_id, tool_name, risk,
                           workspace_revision, request_hash, display_summary,
                           status, requested_by, requested_at, expires_at,
                           decision, decided_by, decided_at
                    FROM coding_approvals
                    WHERE task_id = :task_id AND run_id = :run_id
                      AND tool_call_id = :tool_call_id
                    """
                ),
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                },
            )
            row = result.first()
        return self._approval_from_row(row) if row is not None else None

    async def resolve_tool_approval(
        self,
        *,
        task_id: str,
        approval_id: str,
        owner_id: str,
        decision: ApprovalDecision,
        now: datetime,
    ) -> ApprovalResolutionCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH canonical AS (
                            SELECT candidate.run_id
                            FROM coding_runs candidate
                            WHERE candidate.task_id = :task_id
                            ORDER BY candidate.attempt DESC
                            LIMIT 1
                        )
                        SELECT approval.approval_id, approval.task_id,
                               approval.run_id, approval.tool_call_id,
                               approval.checkpoint_id, approval.tool_name,
                               approval.risk, approval.workspace_revision,
                               approval.request_hash, approval.display_summary,
                               approval.status, approval.requested_by,
                               approval.requested_at, approval.expires_at,
                               approval.decision, approval.decided_by,
                               approval.decided_at,
                               checkpoint.loop_state_json,
                               binding.workspace_revision,
                               canonical.run_id
                        FROM coding_approvals approval
                        JOIN coding_tasks task
                          ON task.task_id = approval.task_id
                        JOIN coding_checkpoints checkpoint
                          ON checkpoint.checkpoint_id = approval.checkpoint_id
                        LEFT JOIN coding_sandbox_bindings binding
                          ON binding.task_id = approval.task_id
                        CROSS JOIN canonical
                        WHERE approval.task_id = :task_id
                          AND approval.approval_id = :approval_id
                          AND task.owner_id = :owner_id
                          AND task.deleted_at IS NULL
                        FOR UPDATE OF approval, task
                        """
                    ),
                    {
                        "task_id": task_id,
                        "approval_id": approval_id,
                        "owner_id": owner_id,
                    },
                )
                row = result.first()
                if row is None:
                    raise ApprovalNotFound(approval_id)
                approval = self._approval_from_row(row)
                if approval.status is not ApprovalStatus.PENDING:
                    raise ApprovalConflict("approval_already_resolved")
                status, conflict_code = self._resolution_status(
                    approval=approval,
                    loop_state=dict(row[17]),
                    current_workspace_revision=row[18],
                    canonical_run_id=row[19],
                    decision=decision,
                    now=now,
                )
                resolved = self._resolved_approval(
                    approval=approval,
                    status=status,
                    decision=decision,
                    owner_id=owner_id,
                    now=now,
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_approvals
                        SET status = :status, decision = :decision,
                            decided_by = :decided_by, decided_at = :decided_at
                        WHERE approval_id = :approval_id
                          AND task_id = :task_id AND status = 'pending'
                        """
                    ),
                    {
                        "approval_id": approval_id,
                        "task_id": task_id,
                        "status": status.value,
                        "decision": (
                            resolved.decision.value
                            if resolved.decision is not None
                            else None
                        ),
                        "decided_by": resolved.decided_by,
                        "decided_at": now,
                    },
                )
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_tasks
                        SET status = 'running', updated_at = :now,
                            last_activity_at = :now
                        WHERE task_id = :task_id
                          AND status = 'waiting_approval'
                        RETURNING task_id
                        """
                    ),
                    {"task_id": task_id, "now": now},
                )
                if updated.first() is None:
                    raise ApprovalConflict("approval_task_state_changed")
                resolution_event = await self._append_event_in_session(
                    session,
                    task_id=task_id,
                    event_type=f"approval.{status.value}",
                    payload=self._approval_event_payload(resolved),
                    now=now,
                    run_id=approval.run_id,
                    tool_call_id=approval.tool_call_id,
                    checkpoint_id=approval.checkpoint_id,
                )
                status_event = await self._append_event_in_session(
                    session,
                    task_id=task_id,
                    event_type="task.status.changed",
                    payload={"status": "running"},
                    now=now,
                    run_id=approval.run_id,
                    checkpoint_id=approval.checkpoint_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ApprovalResolutionCommit(
            resolved,
            (resolution_event, status_event),
            conflict_code,
        )

    async def expire_pending_approvals(
        self, *, limit: int, now: datetime
    ) -> tuple[ApprovalResolutionCommit, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH claimable AS (
                            SELECT approval_id
                            FROM coding_approvals
                            WHERE status = 'pending' AND expires_at <= :now
                            ORDER BY expires_at, approval_id
                            FOR UPDATE SKIP LOCKED
                            LIMIT :limit
                        )
                        UPDATE coding_approvals approval
                        SET status = 'expired', decided_at = :now
                        FROM claimable
                        WHERE approval.approval_id = claimable.approval_id
                        RETURNING approval.approval_id, approval.task_id,
                                  approval.run_id, approval.tool_call_id,
                                  approval.checkpoint_id, approval.tool_name,
                                  approval.risk, approval.workspace_revision,
                                  approval.request_hash,
                                  approval.display_summary, approval.status,
                                  approval.requested_by,
                                  approval.requested_at, approval.expires_at,
                                  approval.decision, approval.decided_by,
                                  approval.decided_at
                        """
                    ),
                    {"now": now, "limit": limit},
                )
                rows = result.all()
                commits = []
                for row in rows:
                    approval = self._approval_from_row(row)
                    await session.execute(
                        text(
                            """
                            UPDATE coding_tasks
                            SET status = 'running', updated_at = :now,
                                last_activity_at = :now
                            WHERE task_id = :task_id
                              AND status = 'waiting_approval'
                            """
                        ),
                        {"task_id": approval.task_id, "now": now},
                    )
                    resolution_event = await self._append_event_in_session(
                        session,
                        task_id=approval.task_id,
                        event_type="approval.expired",
                        payload=self._approval_event_payload(approval),
                        now=now,
                        run_id=approval.run_id,
                        tool_call_id=approval.tool_call_id,
                        checkpoint_id=approval.checkpoint_id,
                    )
                    status_event = await self._append_event_in_session(
                        session,
                        task_id=approval.task_id,
                        event_type="task.status.changed",
                        payload={"status": "running"},
                        now=now,
                        run_id=approval.run_id,
                        checkpoint_id=approval.checkpoint_id,
                    )
                    commits.append(
                        ApprovalResolutionCommit(
                            approval,
                            (resolution_event, status_event),
                        )
                    )
        if commits and self._wake_outbox is not None:
            self._wake_outbox()
        return tuple(commits)

    async def begin_phase(
        self,
        *,
        lease: ExecutionLease,
        kind: CodingPhaseKind,
        now: datetime,
    ) -> PhaseStart:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                active_result = await session.execute(
                    text(
                        """
                        SELECT phase_id, task_id, run_id, phase_kind, attempt,
                               status, started_at, completed_at
                        FROM coding_phases
                        WHERE task_id = :task_id
                          AND run_id = :run_id
                          AND phase_kind = :phase_kind
                          AND status = 'active'
                        ORDER BY attempt DESC
                        LIMIT 1
                        FOR UPDATE
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "phase_kind": kind.value,
                    },
                )
                active = active_result.first()
                if active is not None:
                    return PhaseStart(
                        phase=self._phase_from_row(active),
                        event=None,
                        resumed=True,
                    )
                attempt_result = await session.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(attempt), 0) + 1
                        FROM coding_phases
                        WHERE task_id = :task_id
                          AND phase_kind = :phase_kind
                        """
                    ),
                    {"task_id": lease.task_id, "phase_kind": kind.value},
                )
                attempt_row = attempt_result.first()
                attempt = int(attempt_row[0]) if attempt_row else 1
                phase = CodingPhase(
                    phase_id=(f"cp_{lease.run_id}_{kind.value}_{attempt}"),
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    kind=kind,
                    attempt=attempt,
                    status=CodingPhaseStatus.ACTIVE,
                    started_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_phases
                            (phase_id, task_id, run_id, phase_kind, attempt,
                             status, started_at, completed_at)
                        VALUES
                            (:phase_id, :task_id, :run_id, :phase_kind,
                             :attempt, 'active', :started_at, NULL)
                        """
                    ),
                    {
                        "phase_id": phase.phase_id,
                        "task_id": phase.task_id,
                        "run_id": phase.run_id,
                        "phase_kind": phase.kind.value,
                        "attempt": phase.attempt,
                        "started_at": phase.started_at,
                    },
                )
                event = await self._append_event_in_session(
                    session,
                    task_id=lease.task_id,
                    event_type="phase.started",
                    payload={
                        "phase": kind.value,
                        "attempt": attempt,
                    },
                    now=now,
                    run_id=lease.run_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return PhaseStart(phase=phase, event=event, resumed=False)

    async def commit_phase_checkpoint(
        self,
        *,
        lease: ExecutionLease,
        phase: CodingPhase,
        tool_call_id: str,
        result: Mapping[str, Any],
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        now: datetime,
    ) -> PhaseCheckpointCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                checkpoint = CodingCheckpoint(
                    checkpoint_id=f"cc_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=seq,
                    loop_state=dict(loop_state),
                    workspace_revision=workspace_revision,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "task_id": checkpoint.task_id,
                        "run_id": checkpoint.run_id,
                        "seq": checkpoint.seq,
                        "loop_state": json.dumps(dict(loop_state)),
                        "workspace_revision": workspace_revision,
                        "created_at": now,
                    },
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="phase.completed",
                    payload={
                        "phase": phase.kind.value,
                        "attempt": phase.attempt,
                        **dict(result),
                    },
                    now=now,
                    run_id=lease.run_id,
                    tool_call_id=tool_call_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                )
                completed = replace(
                    phase,
                    status=CodingPhaseStatus.COMPLETED,
                    completed_at=now,
                )
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_phases
                        SET status = 'completed', completed_at = :now
                        WHERE phase_id = :phase_id
                          AND task_id = :task_id
                          AND run_id = :run_id
                          AND status = 'active'
                        RETURNING phase_id
                        """
                    ),
                    {
                        "phase_id": phase.phase_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "now": now,
                    },
                )
                if updated.first() is None:
                    raise StaleExecutionLease(lease.task_id)
        if self._wake_outbox is not None:
            self._wake_outbox()
        return PhaseCheckpointCommit(checkpoint, event, completed)

    async def commit_model_checkpoint(
        self,
        *,
        lease: ExecutionLease,
        event_type: str,
        event_payload: Mapping[str, Any],
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        now: datetime,
    ) -> ModelCheckpointCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                locked = await session.execute(
                    text(
                        """
                        SELECT run_id
                        FROM coding_runs
                        WHERE run_id = :run_id
                          AND task_id = :task_id
                          AND status = 'running'
                        FOR UPDATE
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id},
                )
                if locked.first() is None:
                    raise StaleExecutionLease(lease.task_id)
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                checkpoint = CodingCheckpoint(
                    checkpoint_id=f"cc_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=seq,
                    loop_state=dict(loop_state),
                    workspace_revision=workspace_revision,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "task_id": checkpoint.task_id,
                        "run_id": checkpoint.run_id,
                        "seq": seq,
                        "loop_state": json.dumps(dict(loop_state)),
                        "workspace_revision": workspace_revision,
                        "created_at": now,
                    },
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type=event_type,
                    payload=event_payload,
                    now=now,
                    run_id=lease.run_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ModelCheckpointCommit(checkpoint, event)

    async def start_model_text_part(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        now: datetime,
    ) -> ModelTextPartCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                await self._lock_canonical_running_run(session, lease)
                duplicate = await session.execute(
                    text(
                        """
                        SELECT part_id
                        FROM coding_text_parts
                        WHERE part_id = :part_id
                           OR (task_id = :task_id AND turn_id = :turn_id)
                        LIMIT 1
                        FOR UPDATE
                        """
                    ),
                    {
                        "part_id": part_id,
                        "task_id": lease.task_id,
                        "turn_id": turn_id,
                    },
                )
                if duplicate.first() is not None:
                    raise TextPartConflict("model_text_part_exists")
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                interrupted = await session.execute(
                    text(
                        """
                        UPDATE coding_text_parts
                        SET status = 'interrupted', last_seq = :seq,
                            updated_at = :now
                        WHERE task_id = :task_id
                          AND run_id = :run_id
                          AND status = 'streaming'
                        RETURNING part_id
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "seq": seq,
                        "now": now,
                    },
                )
                interrupted_ids = tuple(sorted(row[0] for row in interrupted))
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_text_parts
                            (part_id, task_id, run_id, turn_id, first_seq,
                             last_seq, status, content, content_bytes,
                             created_at, updated_at)
                        VALUES
                            (:part_id, :task_id, :run_id, :turn_id, :seq,
                             :seq, 'streaming', '', 0, :now, :now)
                        """
                    ),
                    {
                        "part_id": part_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "turn_id": turn_id,
                        "seq": seq,
                        "now": now,
                    },
                )
                part = CodingTextPart(
                    part_id=part_id,
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    turn_id=turn_id,
                    first_seq=seq,
                    last_seq=seq,
                    status=TextPartStatus.STREAMING,
                    content="",
                    content_bytes=0,
                    created_at=now,
                    updated_at=now,
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="model.text_part.started",
                    payload={
                        "part_id": part_id,
                        "status": "streaming",
                        "interrupted_part_ids": list(interrupted_ids),
                    },
                    now=now,
                    run_id=lease.run_id,
                    turn_id=turn_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ModelTextPartCommit(part, event, interrupted_ids)

    async def append_model_text_delta(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        delta: str,
        delta_bytes: int,
        max_part_bytes: int,
        now: datetime,
    ) -> ModelTextPartCommit:
        if not delta or delta_bytes != len(delta.encode("utf-8")):
            raise ValueError("delta_bytes must match a non-empty UTF-8 delta")
        if max_part_bytes < 1:
            raise ValueError("max_part_bytes must be positive")
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                await self._lock_canonical_running_run(session, lease)
                current = await session.execute(
                    text(
                        """
                        SELECT part_id, task_id, run_id, turn_id, first_seq,
                               last_seq, status, content, content_bytes,
                               created_at, updated_at
                        FROM coding_text_parts
                        WHERE part_id = :part_id
                          AND task_id = :task_id
                          AND run_id = :run_id
                          AND turn_id = :turn_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "part_id": part_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "turn_id": turn_id,
                    },
                )
                row = current.first()
                if row is None or row[6] != TextPartStatus.STREAMING.value:
                    raise TextPartConflict("model_text_part_stale")
                part = self._text_part_from_row(row)
                if part.content_bytes + delta_bytes > max_part_bytes:
                    raise TextPartConflict("model_public_text_budget_exceeded")
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                updated = await session.execute(
                    text(
                        """
                        UPDATE coding_text_parts
                        SET content = content || :delta,
                            content_bytes = content_bytes + :delta_bytes,
                            last_seq = :seq, updated_at = :now
                        WHERE part_id = :part_id
                          AND task_id = :task_id
                          AND run_id = :run_id
                          AND turn_id = :turn_id
                          AND status = 'streaming'
                          AND content_bytes + :delta_bytes <= :max_part_bytes
                        RETURNING part_id, task_id, run_id, turn_id, first_seq,
                                  last_seq, status, content, content_bytes,
                                  created_at, updated_at
                        """
                    ),
                    {
                        "part_id": part_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "turn_id": turn_id,
                        "delta": delta,
                        "delta_bytes": delta_bytes,
                        "max_part_bytes": max_part_bytes,
                        "seq": seq,
                        "now": now,
                    },
                )
                updated_row = updated.first()
                if updated_row is None:
                    raise TextPartConflict("model_text_part_stale")
                part = self._text_part_from_row(updated_row)
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="model.text_delta",
                    payload={"part_id": part_id, "delta": delta},
                    now=now,
                    run_id=lease.run_id,
                    turn_id=turn_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ModelTextPartCommit(part, event)

    async def complete_model_text_part(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        now: datetime,
    ) -> ModelTextPartCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                await self._lock_canonical_running_run(session, lease)
                current = await session.execute(
                    text(
                        """
                        SELECT part_id, task_id, run_id, turn_id, first_seq,
                               last_seq, status, content, content_bytes,
                               created_at, updated_at
                        FROM coding_text_parts
                        WHERE part_id = :part_id
                          AND task_id = :task_id
                          AND run_id = :run_id
                          AND turn_id = :turn_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "part_id": part_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "turn_id": turn_id,
                    },
                )
                row = current.first()
                if row is None or row[6] != TextPartStatus.STREAMING.value:
                    raise TextPartConflict("model_text_part_stale")
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                completed = await session.execute(
                    text(
                        """
                        UPDATE coding_text_parts
                        SET status = 'completed', last_seq = :seq,
                            updated_at = :now
                        WHERE part_id = :part_id AND status = 'streaming'
                        RETURNING part_id, task_id, run_id, turn_id, first_seq,
                                  last_seq, status, content, content_bytes,
                                  created_at, updated_at
                        """
                    ),
                    {"part_id": part_id, "seq": seq, "now": now},
                )
                completed_row = completed.first()
                if completed_row is None:
                    raise TextPartConflict("model_text_part_stale")
                part = self._text_part_from_row(completed_row)
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="model.text_part.completed",
                    payload={"part_id": part_id, "status": "completed"},
                    now=now,
                    run_id=lease.run_id,
                    turn_id=turn_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return ModelTextPartCommit(part, event)

    async def apply_steering_at_safe_point(
        self,
        *,
        lease: ExecutionLease,
        checkpoint: CodingCheckpoint,
        worker_id: str,
        claim_expires_at: datetime,
        now: datetime,
    ) -> SteeringApplication | None:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                claimed = await session.execute(
                    text(
                        """
                        WITH claimable AS (
                            SELECT steering_id
                            FROM coding_steering_requests
                            WHERE task_id = :task_id
                              AND mode = 'safe_point'
                              AND (
                                  status = 'pending'
                                  OR (
                                      status = 'claimed'
                                      AND claim_expires_at <= :now
                                  )
                              )
                            ORDER BY requested_at, steering_id
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE coding_steering_requests request
                        SET status = 'claimed',
                            claimed_by = :worker_id,
                            claimed_at = :now,
                            claim_expires_at = :claim_expires_at
                        FROM claimable
                        WHERE request.steering_id = claimable.steering_id
                        RETURNING request.steering_id, request.task_id,
                                  request.mode, request.instruction,
                                  request.requested_at
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "worker_id": worker_id,
                        "now": now,
                        "claim_expires_at": claim_expires_at,
                    },
                )
                request_row = claimed.first()
                if request_row is None:
                    return None
                request = SteeringRequest(
                    steering_id=request_row[0],
                    task_id=request_row[1],
                    mode=SteeringMode(request_row[2]),
                    instruction=request_row[3],
                    requested_at=request_row[4],
                )
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                loop_state = dict(checkpoint.loop_state)
                loop_state["phase_index"] = -1
                loop_state["current_instruction"] = request.instruction
                loop_state["pending_instruction"] = None
                steering_checkpoint = CodingCheckpoint(
                    checkpoint_id=f"cc_steer_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=seq,
                    loop_state=loop_state,
                    workspace_revision=checkpoint.workspace_revision,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": steering_checkpoint.checkpoint_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "seq": seq,
                        "loop_state": json.dumps(loop_state),
                        "workspace_revision": checkpoint.workspace_revision,
                        "created_at": now,
                    },
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="steer.applied",
                    payload={
                        "steering_id": request.steering_id,
                        "mode": request.mode.value,
                        "instruction": request.instruction,
                    },
                    now=now,
                    run_id=lease.run_id,
                    checkpoint_id=steering_checkpoint.checkpoint_id,
                )
                previous_result = await session.execute(
                    text(
                        """
                        SELECT run_id, task_id, attempt, status,
                               resume_from_checkpoint_id, started_at, completed_at
                        FROM coding_runs
                        WHERE run_id = :run_id AND task_id = :task_id
                        FOR UPDATE
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id},
                )
                previous_row = previous_result.first()
                if previous_row is None:
                    raise StaleExecutionLease(lease.task_id)
                previous_run = self._run_from_row(previous_row)
                cancelled_run = replace(
                    previous_run,
                    status=CodingRunStatus.CANCELLED,
                    completed_at=now,
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_runs
                        SET status = 'cancelled', completed_at = :now
                        WHERE run_id = :run_id
                          AND task_id = :task_id
                          AND status = 'running'
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id, "now": now},
                )
                run = CodingRun(
                    run_id=f"cr_{uuid4().hex}",
                    task_id=lease.task_id,
                    attempt=previous_run.attempt + 1,
                    status=CodingRunStatus.RUNNING,
                    resume_from_checkpoint_id=steering_checkpoint.checkpoint_id,
                    started_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_runs
                            (run_id, task_id, attempt, status,
                             resume_from_checkpoint_id, started_at, completed_at)
                        VALUES
                            (:run_id, :task_id, :attempt, 'running',
                             :checkpoint_id, :now, NULL)
                        """
                    ),
                    {
                        "run_id": run.run_id,
                        "task_id": run.task_id,
                        "attempt": run.attempt,
                        "checkpoint_id": steering_checkpoint.checkpoint_id,
                        "now": now,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_steering_requests
                        SET status = 'applied',
                            applied_checkpoint_id = :checkpoint_id,
                            claim_expires_at = NULL
                        WHERE steering_id = :steering_id
                          AND status = 'claimed'
                          AND claimed_by = :worker_id
                        """
                    ),
                    {
                        "steering_id": request.steering_id,
                        "checkpoint_id": steering_checkpoint.checkpoint_id,
                        "worker_id": worker_id,
                    },
                )
                lease_result = await session.execute(
                    text(
                        """
                        UPDATE coding_run_leases
                        SET run_id = :new_run_id,
                            worker_id = :worker_id,
                            fencing_token = fencing_token + 1,
                            acquired_at = :now,
                            heartbeat_at = :now,
                            expires_at = :expires_at
                        WHERE task_id = :task_id
                          AND run_id = :old_run_id
                          AND fencing_token = :fencing_token
                        RETURNING task_id, run_id, worker_id, fencing_token,
                                  acquired_at, expires_at, FALSE AS recovered
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "old_run_id": lease.run_id,
                        "new_run_id": run.run_id,
                        "worker_id": worker_id,
                        "fencing_token": lease.fencing_token,
                        "now": now,
                        "expires_at": claim_expires_at,
                    },
                )
                lease_row = lease_result.first()
                if lease_row is None:
                    raise StaleExecutionLease(lease.task_id)
                next_lease = self._lease_from_row(lease_row)
        if self._wake_outbox is not None:
            self._wake_outbox()
        return SteeringApplication(
            request=replace(
                request,
                applied_checkpoint_id=steering_checkpoint.checkpoint_id,
            ),
            checkpoint=steering_checkpoint,
            previous_run=cancelled_run,
            run=run,
            lease=next_lease,
            event=event,
        )

    async def commit_interruption(
        self,
        *,
        lease: ExecutionLease,
        request: SteeringRequest,
        workspace_revision: str,
        process_stopped: bool,
        now: datetime,
    ) -> SteeringApplication:
        if not process_stopped:
            raise ValueError("process must be stopped before interruption commit")
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                seq = await self._allocate_sequence_in_session(
                    session, task_id=lease.task_id, now=now
                )
                checkpoint = CodingCheckpoint(
                    checkpoint_id=f"cc_interrupt_{uuid4().hex}",
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=seq,
                    loop_state={
                        "phase_index": -1,
                        "transcript": [],
                        "current_instruction": request.instruction,
                        "pending_instruction": None,
                    },
                    workspace_revision=workspace_revision,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "task_id": checkpoint.task_id,
                        "run_id": checkpoint.run_id,
                        "seq": checkpoint.seq,
                        "loop_state": json.dumps(dict(checkpoint.loop_state)),
                        "workspace_revision": workspace_revision,
                        "created_at": now,
                    },
                )
                event = await self._insert_event_in_session(
                    session,
                    task_id=lease.task_id,
                    seq=seq,
                    event_type="run.interrupted",
                    payload={
                        "steering_id": request.steering_id,
                        "process_stopped": True,
                    },
                    now=now,
                    run_id=lease.run_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                )
                previous_result = await session.execute(
                    text(
                        """
                        SELECT run_id, task_id, attempt, status,
                               resume_from_checkpoint_id, started_at, completed_at
                        FROM coding_runs
                        WHERE run_id = :run_id AND task_id = :task_id
                        FOR UPDATE
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id},
                )
                previous_row = previous_result.first()
                if previous_row is None:
                    raise StaleExecutionLease(lease.task_id)
                previous = self._run_from_row(previous_row)
                cancelled = replace(
                    previous,
                    status=CodingRunStatus.CANCELLED,
                    completed_at=now,
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_runs
                        SET status = 'cancelled', completed_at = :now
                        WHERE run_id = :run_id AND task_id = :task_id
                        """
                    ),
                    {"run_id": lease.run_id, "task_id": lease.task_id, "now": now},
                )
                run = CodingRun(
                    run_id=f"cr_{uuid4().hex}",
                    task_id=lease.task_id,
                    attempt=previous.attempt + 1,
                    status=CodingRunStatus.RUNNING,
                    resume_from_checkpoint_id=checkpoint.checkpoint_id,
                    started_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_runs
                            (run_id, task_id, attempt, status,
                             resume_from_checkpoint_id, started_at, completed_at)
                        VALUES
                            (:run_id, :task_id, :attempt, 'running',
                             :checkpoint_id, :now, NULL)
                        """
                    ),
                    {
                        "run_id": run.run_id,
                        "task_id": run.task_id,
                        "attempt": run.attempt,
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "now": now,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE coding_steering_requests
                        SET status = 'applied',
                            applied_checkpoint_id = :checkpoint_id,
                            claimed_by = :worker_id,
                            claimed_at = :now,
                            claim_expires_at = NULL
                        WHERE steering_id = :steering_id
                          AND task_id = :task_id
                          AND status IN ('pending', 'claimed')
                        """
                    ),
                    {
                        "steering_id": request.steering_id,
                        "task_id": lease.task_id,
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "worker_id": lease.worker_id,
                        "now": now,
                    },
                )
                lease_result = await session.execute(
                    text(
                        """
                        UPDATE coding_run_leases
                        SET run_id = :new_run_id,
                            fencing_token = fencing_token + 1,
                            acquired_at = :now,
                            heartbeat_at = :now,
                            expires_at = :expires_at
                        WHERE task_id = :task_id
                          AND run_id = :old_run_id
                          AND worker_id = :worker_id
                          AND fencing_token = :fencing_token
                        RETURNING task_id, run_id, worker_id, fencing_token,
                                  acquired_at, expires_at, FALSE AS recovered
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "old_run_id": lease.run_id,
                        "new_run_id": run.run_id,
                        "worker_id": lease.worker_id,
                        "fencing_token": lease.fencing_token,
                        "now": now,
                        "expires_at": lease.expires_at,
                    },
                )
                lease_row = lease_result.first()
                if lease_row is None:
                    raise StaleExecutionLease(lease.task_id)
                next_lease = self._lease_from_row(lease_row)
        if self._wake_outbox is not None:
            self._wake_outbox()
        applied_request = replace(
            request, applied_checkpoint_id=checkpoint.checkpoint_id
        )
        return SteeringApplication(
            applied_request,
            checkpoint,
            cancelled,
            run,
            next_lease,
            event,
        )

    async def claim_workspace_edits_at_safe_point(
        self,
        *,
        lease: ExecutionLease,
        checkpoint: CodingCheckpoint,
        limit: int,
        now: datetime,
    ) -> WorkspaceEditApplication | None:
        if limit < 1:
            raise ValueError("limit must be positive")
        result: WorkspaceEditApplication | None = None
        async with await self._session_factory() as session:
            async with session.begin():
                await self._validate_lease_in_session(session, lease, now=now)
                await self._lock_canonical_running_run(session, lease)
                selected = await session.execute(
                    text(
                        """
                        SELECT edit_id, task_id, run_id, path, base_revision,
                               resulting_revision, status, content_digest,
                               content_bytes, created_at, committed_at,
                               applied_checkpoint_id
                        FROM coding_workspace_edits
                        WHERE task_id = :task_id
                          AND status = 'committed'
                          AND applied_checkpoint_id IS NULL
                        ORDER BY resulting_revision::BIGINT, edit_id
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {
                        "task_id": lease.task_id,
                        "limit": limit,
                    },
                )
                rows = selected.fetchall()
                if not rows:
                    return None
                edits = tuple(self._workspace_edit_from_row(row) for row in rows)
                sequences = [
                    await self._allocate_sequence_in_session(
                        session,
                        task_id=lease.task_id,
                        now=now,
                    )
                    for _ in edits
                ]
                checkpoint_id = f"cc_workspace_{uuid4().hex}"
                pending = [
                    {
                        "edit_id": edit.edit_id,
                        "path": edit.path,
                        "resulting_revision": edit.resulting_revision,
                    }
                    for edit in edits
                ]
                loop_state = {
                    **dict(checkpoint.loop_state),
                    "pending_workspace_edits": pending,
                }
                applied_checkpoint = CodingCheckpoint(
                    checkpoint_id=checkpoint_id,
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    seq=sequences[-1],
                    loop_state=loop_state,
                    workspace_revision=checkpoint.workspace_revision,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_checkpoints
                            (checkpoint_id, task_id, run_id, seq,
                             loop_state_json, workspace_revision, created_at)
                        VALUES
                            (:checkpoint_id, :task_id, :run_id, :seq,
                             CAST(:loop_state AS JSONB),
                             :workspace_revision, :created_at)
                        """
                    ),
                    {
                        "checkpoint_id": checkpoint_id,
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "seq": sequences[-1],
                        "loop_state": json.dumps(loop_state),
                        "workspace_revision": checkpoint.workspace_revision,
                        "created_at": now,
                    },
                )
                applied_edits: list[CodingWorkspaceEdit] = []
                events: list[CodingEvent] = []
                for edit, seq in zip(edits, sequences, strict=True):
                    updated = await session.execute(
                        text(
                            """
                            UPDATE coding_workspace_edits
                            SET status = 'applied',
                                applied_checkpoint_id = :checkpoint_id
                            WHERE edit_id = :edit_id
                              AND status = 'committed'
                              AND applied_checkpoint_id IS NULL
                            RETURNING edit_id
                            """
                        ),
                        {
                            "edit_id": edit.edit_id,
                            "checkpoint_id": checkpoint_id,
                        },
                    )
                    if updated.first() is None:
                        raise StaleExecutionLease(lease.task_id)
                    applied = replace(
                        edit,
                        status=WorkspaceEditStatus.APPLIED,
                        applied_checkpoint_id=checkpoint_id,
                    )
                    applied_edits.append(applied)
                    events.append(
                        await self._insert_event_in_session(
                            session,
                            task_id=lease.task_id,
                            seq=seq,
                            event_type="workspace.user_edit.synced",
                            payload={
                                "edit_id": applied.edit_id,
                                "path": applied.path,
                                "resulting_revision": (
                                    applied.resulting_revision
                                ),
                                "status": "agent_synced",
                                "applied_checkpoint_id": checkpoint_id,
                            },
                            now=now,
                            run_id=lease.run_id,
                            checkpoint_id=checkpoint_id,
                        )
                    )
                result = WorkspaceEditApplication(
                    tuple(applied_edits),
                    applied_checkpoint,
                    tuple(events),
                )
        if result is not None and self._wake_outbox is not None:
            self._wake_outbox()
        return result

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
    def _approval_from_row(row) -> CodingApproval:
        return CodingApproval(
            approval_id=row[0],
            task_id=row[1],
            run_id=row[2],
            tool_call_id=row[3],
            checkpoint_id=row[4],
            tool_name=row[5],
            risk=ToolRisk(row[6]),
            workspace_revision=row[7],
            request_hash=row[8],
            display_summary=dict(row[9]),
            status=ApprovalStatus(row[10]),
            requested_by=row[11],
            requested_at=row[12],
            expires_at=row[13],
            decision=ApprovalDecision(row[14]) if row[14] is not None else None,
            decided_by=row[15],
            decided_at=row[16],
        )

    @staticmethod
    def _text_part_from_row(row) -> CodingTextPart:
        return CodingTextPart(
            part_id=row[0],
            task_id=row[1],
            run_id=row[2],
            turn_id=row[3],
            first_seq=int(row[4]),
            last_seq=int(row[5]),
            status=TextPartStatus(row[6]),
            content=row[7],
            content_bytes=int(row[8]),
            created_at=row[9],
            updated_at=row[10],
        )

    @staticmethod
    def _approval_binding(
        *,
        lease: ExecutionLease,
        tool_call: ToolCallCompleted,
        validated: ValidatedToolCall,
        checkpoint_id: str,
        workspace_revision: str,
    ) -> Mapping[str, object]:
        return {
            "task_id": lease.task_id,
            "run_id": lease.run_id,
            "tool_call_id": tool_call.tool_call_id,
            "tool_name": validated.name,
            "normalized_input": dict(validated.input),
            "checkpoint_id": checkpoint_id,
            "workspace_revision": workspace_revision,
        }

    @staticmethod
    def _approval_event_payload(approval: CodingApproval) -> Mapping[str, object]:
        return {
            "approval_id": approval.approval_id,
            "tool_name": approval.tool_name,
            "risk": approval.risk.value,
            "status": approval.status.value,
            "requested_at": approval.requested_at.isoformat(),
            "expires_at": approval.expires_at.isoformat(),
            "display_summary": dict(approval.display_summary),
        }

    @staticmethod
    def _resolution_status(
        *,
        approval: CodingApproval,
        loop_state: Mapping[str, object],
        current_workspace_revision: str | None,
        canonical_run_id: str,
        decision: ApprovalDecision,
        now: datetime,
    ) -> tuple[ApprovalStatus, str | None]:
        if approval.expires_at <= now:
            return ApprovalStatus.EXPIRED, "approval_expired"
        calls = loop_state.get("pending_tool_calls", [])
        call = next(
            (
                item
                for item in calls
                if isinstance(item, Mapping)
                and item.get("tool_call_id") == approval.tool_call_id
            ),
            None,
        )
        if call is None:
            return ApprovalStatus.INVALIDATED, "approval_invalidated"
        expected_hash = canonical_approval_hash(
            {
                "task_id": approval.task_id,
                "run_id": approval.run_id,
                "tool_call_id": approval.tool_call_id,
                "tool_name": call.get("name"),
                "normalized_input": call.get("input"),
                "checkpoint_id": approval.checkpoint_id,
                "workspace_revision": approval.workspace_revision,
            }
        )
        if (
            approval.run_id != canonical_run_id
            or current_workspace_revision != approval.workspace_revision
            or expected_hash != approval.request_hash
        ):
            return ApprovalStatus.INVALIDATED, "approval_invalidated"
        if decision is ApprovalDecision.APPROVE:
            return ApprovalStatus.APPROVED, None
        return ApprovalStatus.DENIED, None

    @staticmethod
    def _resolved_approval(
        *,
        approval: CodingApproval,
        status: ApprovalStatus,
        decision: ApprovalDecision,
        owner_id: str,
        now: datetime,
    ) -> CodingApproval:
        if status in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}:
            return replace(
                approval,
                status=status,
                decision=decision,
                decided_by=owner_id,
                decided_at=now,
            )
        return replace(approval, status=status, decided_at=now)

    @staticmethod
    def _lease_params(lease: ExecutionLease, **extra) -> dict[str, Any]:
        return {
            "task_id": lease.task_id,
            "run_id": lease.run_id,
            "worker_id": lease.worker_id,
            "fencing_token": lease.fencing_token,
            **extra,
        }

    async def _validate_lease_in_session(
        self, session, lease: ExecutionLease, *, now: datetime
    ) -> None:
        result = await session.execute(
            text(
                """
                SELECT task_id
                FROM coding_run_leases
                WHERE task_id = :task_id
                  AND run_id = :run_id
                  AND worker_id = :worker_id
                  AND fencing_token = :fencing_token
                  AND expires_at > :now
                FOR UPDATE
                """
            ),
            self._lease_params(lease, now=now),
        )
        if result.first() is None:
            raise StaleExecutionLease(lease.task_id)

    @staticmethod
    async def _lock_canonical_running_run(session, lease: ExecutionLease) -> None:
        result = await session.execute(
            text(
                """
                SELECT run.run_id
                FROM coding_runs AS run
                JOIN coding_tasks AS task ON task.task_id = run.task_id
                WHERE run.run_id = :run_id
                  AND run.task_id = :task_id
                  AND run.status = 'running'
                  AND task.status = 'running'
                  AND run.attempt = (
                      SELECT MAX(candidate.attempt)
                      FROM coding_runs AS candidate
                      WHERE candidate.task_id = :task_id
                  )
                FOR UPDATE OF run
                """
            ),
            {"run_id": lease.run_id, "task_id": lease.task_id},
        )
        if result.first() is None:
            raise StaleExecutionLease(lease.task_id)

    @staticmethod
    def _phase_from_row(row) -> CodingPhase:
        return CodingPhase(
            phase_id=row[0],
            task_id=row[1],
            run_id=row[2],
            kind=CodingPhaseKind(row[3]),
            attempt=int(row[4]),
            status=CodingPhaseStatus(row[5]),
            started_at=row[6],
            completed_at=row[7],
        )

    @staticmethod
    def _run_from_row(row) -> CodingRun:
        return CodingRun(
            run_id=row[0],
            task_id=row[1],
            attempt=int(row[2]),
            status=CodingRunStatus(row[3]),
            resume_from_checkpoint_id=row[4],
            started_at=row[5],
            completed_at=row[6],
        )

    @staticmethod
    def _workspace_edit_from_row(row) -> CodingWorkspaceEdit:
        return CodingWorkspaceEdit(
            edit_id=row[0],
            task_id=row[1],
            run_id=row[2],
            path=row[3],
            base_revision=row[4],
            resulting_revision=row[5],
            status=WorkspaceEditStatus(row[6]),
            content_digest=row[7],
            content_bytes=int(row[8]),
            created_at=row[9],
            committed_at=row[10],
            applied_checkpoint_id=row[11],
        )

    async def _allocate_sequence_in_session(
        self, session, *, task_id: str, now: datetime
    ) -> int:
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
        return int(row[0])

    async def _append_event_in_session(
        self,
        session,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> CodingEvent:
        seq = await self._allocate_sequence_in_session(
            session, task_id=task_id, now=now
        )
        return await self._insert_event_in_session(
            session,
            task_id=task_id,
            seq=seq,
            event_type=event_type,
            payload=payload,
            now=now,
            run_id=run_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            checkpoint_id=checkpoint_id,
        )

    async def _insert_event_in_session(
        self,
        session,
        *,
        task_id: str,
        seq: int,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> CodingEvent:
        event = CodingEvent(
            version=1,
            task_id=task_id,
            seq=seq,
            event_id=f"ce_{uuid4().hex}",
            type=event_type,
            payload=dict(payload),
            created_at=now,
            run_id=run_id,
            turn_id=turn_id,
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
                     :run_id, :turn_id, :tool_call_id, :checkpoint_id)
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
                "turn_id": turn_id,
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

    async def claim_pending_steering(self, task_id: str) -> SteeringRequest | None:
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
