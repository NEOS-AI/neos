from datetime import UTC, datetime

import pytest

from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.domain.approvals import ApprovalStatus
from neos.coding.tools.registry import ToolRisk
from neos.coding.repositories.projection_repository import (
    CodingCheckpointRow,
    CodingPhaseRow,
    CodingProjectionRows,
    CodingRunRow,
    CodingTaskRow,
    CodingTextPartRow,
    CodingToolExecutionRow,
    CodingWorkspaceEditRow,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class ProjectionFixtureRepository:
    def __init__(self, *, head_seq: int) -> None:
        self.head_seq = head_seq

    async def get_owned_snapshot(self, task_id: str, owner_id: str):
        if (task_id, owner_id) != ("ct_1", "u1"):
            return None
        phases = tuple(
            CodingPhaseRow(
                phase_id=f"phase_{index}",
                run_id="cr_1" if attempt == 1 else "cr_2",
                kind=kind,
                attempt=attempt,
                status="completed" if index < 3 else "active",
                started_at=NOW,
                completed_at=NOW if index < 3 else None,
            )
            for index, (kind, attempt) in enumerate(
                [
                    ("understand", 1),
                    ("plan", 1),
                    ("implement", 1),
                    ("understand", 2),
                ]
            )
        )
        return CodingProjectionRows(
            task=CodingTaskRow(
                task_id="ct_1",
                status="running",
                version=2,
                last_seq=self.head_seq,
                created_at=NOW,
                updated_at=NOW,
            ),
            runs=(
                CodingRunRow("cr_1", 1, "cancelled", None),
                CodingRunRow("cr_2", 2, "running", "cc_10"),
            ),
            phases=phases,
            tools=(
                CodingToolExecutionRow(
                    "tool_1",
                    "cr_1",
                    "completed",
                    {
                        "preview": "app.py:12",
                        "env": {"TOKEN": "secret-token"},
                    },
                ),
            ),
            approvals=({
                "approval_id": "ca_1", "tool_name": "write_file.v1",
                "risk": "workspace_write", "status": "pending",
                "requested_at": NOW, "expires_at": NOW,
                "display_summary": {"path": "app.py"},
            },),
            parts=(
                CodingTextPartRow(
                    "part_1", "cr_2", "turn_1", "completed", "안녕", 8, 10
                ),
                CodingTextPartRow(
                    "part_2", "cr_2", "turn_2", "streaming", "계속", 13, 14
                ),
            ),
            workspace_edits=(
                CodingWorkspaceEditRow(
                    "cwe_1",
                    "app.py",
                    "11",
                    "12",
                    "applied",
                    "cc_12",
                ),
            ),
            todos=({"content": "Run tests", "status": "pending"},),
            latest_checkpoint=CodingCheckpointRow(
                "cc_12",
                "cr_2",
                12,
                {
                    "phase_index": 0,
                    "changed_files": ["app.py"],
                    "transcript": (
                        {
                            "role": "assistant",
                            "content": (
                                {
                                    "type": "tool_use",
                                    "tool_call_id": "tool_1",
                                    "name": "read_file.v1",
                                    "input": {"path": "app.py"},
                                },
                            ),
                        },
                    ),
                },
                "rev_12",
                NOW,
            ),
            head_seq=self.head_seq,
        )


async def test_snapshot_is_one_consistent_head_projection() -> None:
    service = CodingSnapshotService(ProjectionFixtureRepository(head_seq=14))

    snapshot = await service.get_owned("ct_1", "u1")

    assert snapshot is not None
    assert snapshot.head_seq == 14
    assert snapshot.active_run is not None
    assert snapshot.active_run.run_id == "cr_2"
    assert [(phase.kind.value, phase.attempt) for phase in snapshot.phases] == [
        ("understand", 1),
        ("plan", 1),
        ("implement", 1),
        ("understand", 2),
    ]
    assert snapshot.latest_checkpoint is not None
    assert snapshot.latest_checkpoint.seq <= snapshot.head_seq
    assert snapshot.workspace.changed_files == ("app.py",)
    assert snapshot.approvals[0].status is ApprovalStatus.PENDING
    assert snapshot.approvals[0].risk is ToolRisk.WORKSPACE_WRITE
    assert [part.content for part in snapshot.parts] == ["안녕", "계속"]
    assert [part.status.value for part in snapshot.parts] == [
        "completed",
        "streaming",
    ]
    assert snapshot.workspace.user_edits[0].status == "agent_synced"
    assert snapshot.workspace.user_edits[0].applied_checkpoint_id == "cc_12"
    assert snapshot.tools[0].tool_call_id == "tool_1"
    assert snapshot.tools[0].status == "completed"
    assert snapshot.tools[0].result == {
        "preview": "app.py:12",
        "env": {"TOKEN": "secret-token"},
    }
    assert snapshot.tools[0].name == "read_file.v1"
    assert snapshot.tools[0].preview == "app.py:12"
    assert "secret-token" not in (snapshot.tools[0].preview or "")


async def test_snapshot_is_owner_scoped() -> None:
    service = CodingSnapshotService(ProjectionFixtureRepository(head_seq=14))

    assert await service.get_owned("ct_1", "foreign") is None


@pytest.mark.no_db
async def test_snapshot_active_children_empty_when_flag_off() -> None:
    service = CodingSnapshotService(ProjectionFixtureRepository(head_seq=14))

    snapshot = await service.get_owned("ct_1", "u1")

    assert snapshot is not None
    assert snapshot.active_children == ()


@pytest.mark.no_db
async def test_snapshot_exposes_opaque_active_children() -> None:
    from dataclasses import replace

    class ChildrenRepository(ProjectionFixtureRepository):
        async def get_owned_snapshot(self, task_id: str, owner_id: str):
            rows = await super().get_owned_snapshot(task_id, owner_id)
            if rows is None or rows.latest_checkpoint is None:
                return rows
            loop_state = dict(rows.latest_checkpoint.loop_state)
            loop_state["active_children"] = [
                {"run_id": "sa_1", "status": "running", "spec": "explore"},
                {"run_id": "sa_2", "tool_call_id": "s2"},
            ]
            return replace(
                rows,
                latest_checkpoint=replace(
                    rows.latest_checkpoint, loop_state=loop_state
                ),
            )

    snapshot = await CodingSnapshotService(
        ChildrenRepository(head_seq=14)
    ).get_owned("ct_1", "u1")

    assert snapshot is not None
    assert [child.run_id for child in snapshot.active_children] == ["sa_1", "sa_2"]
    assert snapshot.active_children[0].status == "running"
    assert snapshot.active_children[0].spec == "explore"
    assert snapshot.active_children[1].status is None
    assert snapshot.active_children[1].spec is None
    assert not hasattr(snapshot.active_children[1], "tool_call_id") or not getattr(
        snapshot.active_children[1], "tool_call_id", None
    )


class FakeResult:
    def __init__(self, *, first=None, rows=()) -> None:
        self._first = first
        self._rows = list(rows)

    def first(self):
        return self._first

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self) -> None:
        self.sql = []
        self.results = [FakeResult(first=None)]

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        if str(statement).startswith("SET TRANSACTION"):
            return FakeResult()
        return self.results.pop(0)


async def test_postgres_projection_uses_repeatable_read_and_owner_scope() -> None:
    from neos.coding.repositories.projection_repository import (
        PostgresCodingProjectionRepository,
    )

    session = FakeSession()

    async def session_factory():
        return session

    repository = PostgresCodingProjectionRepository(session_factory)

    assert await repository.get_owned_snapshot("ct_1", "u1") is None
    sql = "\n".join(session.sql)
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in sql
    assert "owner_id = :owner_id" in sql
