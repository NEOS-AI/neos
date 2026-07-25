from datetime import UTC, datetime, timedelta

from neos.coding.domain.durability import ExecutionLease
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
)
from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditStatus,
)
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def committed(edit_id: str, path: str, revision: str) -> CodingWorkspaceEdit:
    return CodingWorkspaceEdit(
        edit_id=edit_id,
        task_id="ct_1",
        run_id="cr_1",
        path=path,
        base_revision=str(int(revision) - 1),
        resulting_revision=revision,
        status=WorkspaceEditStatus.COMMITTED,
        content_digest=f"sha256:{edit_id}",
        content_bytes=5,
        created_at=NOW,
        committed_at=NOW,
        applied_checkpoint_id=None,
    )


async def test_committed_edits_are_applied_once_with_checkpoint() -> None:
    run = CodingRun(
        "cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW
    )
    repository = InMemoryCodingRunRepository(
        active_run=run,
        workspace_edits=[
            committed("cwe_b", "src/b.py", "13"),
            committed("cwe_a", "src/a.py", "12"),
        ],
    )
    repository.created_runs.append(run)
    repository.task_statuses["ct_1"] = "running"
    lease = ExecutionLease(
        "ct_1",
        "cr_1",
        "worker",
        1,
        NOW,
        NOW + timedelta(minutes=1),
    )
    repository.execution_leases["ct_1"] = lease
    checkpoint = CodingCheckpoint(
        "cc_1",
        "ct_1",
        "cr_1",
        1,
        {
            "phase_index": 0,
            "current_instruction": "Fix it",
            "transcript": [],
        },
        "11",
        NOW,
    )

    first = await repository.claim_workspace_edits_at_safe_point(
        lease=lease,
        checkpoint=checkpoint,
        limit=20,
        now=NOW,
    )
    second = await repository.claim_workspace_edits_at_safe_point(
        lease=lease,
        checkpoint=first.checkpoint,
        limit=20,
        now=NOW,
    )

    assert [item.path for item in first.edits] == ["src/a.py", "src/b.py"]
    assert second is None
    assert all(
        item.applied_checkpoint_id == first.checkpoint.checkpoint_id
        for item in repository.workspace_edits.values()
    )
    assert all(event.type == "workspace.user_edit.synced" for event in first.events)
    assert all("content_digest" not in event.payload for event in first.events)


async def test_safe_point_claim_respects_batch_limit() -> None:
    run = CodingRun(
        "cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW
    )
    repository = InMemoryCodingRunRepository(
        active_run=run,
        workspace_edits=[
            committed("cwe_1", "1.py", "2"),
            committed("cwe_2", "2.py", "3"),
        ],
    )
    repository.created_runs.append(run)
    repository.task_statuses["ct_1"] = "running"
    lease = ExecutionLease(
        "ct_1", "cr_1", "worker", 1, NOW, NOW + timedelta(minutes=1)
    )
    repository.execution_leases["ct_1"] = lease
    checkpoint = CodingCheckpoint(
        "cc_1", "ct_1", "cr_1", 1, {}, "1", NOW
    )

    applied = await repository.claim_workspace_edits_at_safe_point(
        lease=lease, checkpoint=checkpoint, limit=1, now=NOW
    )

    assert len(applied.edits) == 1
    assert sum(
        edit.status is WorkspaceEditStatus.COMMITTED
        for edit in repository.workspace_edits.values()
    ) == 1


async def test_pending_edit_survives_safe_point_run_replacement() -> None:
    old_edit = committed("cwe_1", "src/app.py", "2")
    run = CodingRun(
        "cr_2", "ct_1", 2, CodingRunStatus.RUNNING, "cc_steer", NOW
    )
    repository = InMemoryCodingRunRepository(
        active_run=run,
        workspace_edits=[old_edit],
    )
    repository.created_runs.append(run)
    repository.task_statuses["ct_1"] = "running"
    lease = ExecutionLease(
        "ct_1", "cr_2", "worker", 2, NOW, NOW + timedelta(minutes=1)
    )
    repository.execution_leases["ct_1"] = lease
    checkpoint = CodingCheckpoint(
        "cc_steer", "ct_1", "cr_2", 3, {}, "2", NOW
    )

    applied = await repository.claim_workspace_edits_at_safe_point(
        lease=lease,
        checkpoint=checkpoint,
        limit=20,
        now=NOW,
    )

    assert [edit.edit_id for edit in applied.edits] == ["cwe_1"]
    assert applied.events[0].run_id == "cr_2"
