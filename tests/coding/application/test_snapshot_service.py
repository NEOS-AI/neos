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


@pytest.mark.no_db
async def test_snapshot_carries_jev_verdicts_shaped_like_their_events() -> None:
    """A reconnect starts from the snapshot, so a verdict only the live stream
    carried would vanish on refresh. The verdict for a call parked on approval
    has no execution row, so it must survive without one.
    """
    from dataclasses import replace

    from neos.coding.repositories.projection_repository import CodingToolRiskRow

    scored = {
        "probability": 0.62,
        "band": "middle",
        "low_below": 0.3,
        "high_at_or_above": 0.8,
        "rubric_digest": "f5faf377",
        "model": "jev-1.13.0",
        "static_outcome": "allow",
        "would_be_outcome": "require_approval",
        "enforced": False,
        "tool": "execute.v1",
        "tool_call_id": "t_parked",
    }

    class RiskRepository(ProjectionFixtureRepository):
        async def get_owned_snapshot(self, task_id: str, owner_id: str):
            rows = await super().get_owned_snapshot(task_id, owner_id)
            return replace(
                rows,
                tool_risks=(
                    CodingToolRiskRow("t_parked", "jev_risk_scored", 9, scored),
                    CodingToolRiskRow(
                        "t_down",
                        "jev_unavailable",
                        11,
                        {"reason": "TimeoutError", "enforced": False},
                    ),
                ),
            )

    snapshot = await CodingSnapshotService(RiskRepository(head_seq=14)).get_owned(
        "ct_1", "u1"
    )

    assert snapshot is not None
    by_id = {risk.tool_call_id: risk for risk in snapshot.tool_risks}
    assert sorted(by_id) == ["t_down", "t_parked"]
    assert by_id["t_parked"].kind == "jev_risk_scored"
    assert by_id["t_parked"].payload == scored
    assert by_id["t_down"].kind == "jev_unavailable"
    assert by_id["t_down"].seq == 11
    # No execution row for either call -- the verdict stands on its own.
    assert not {t.tool_call_id for t in snapshot.tools} & set(by_id)


def test_projection_reads_the_same_kinds_the_gate_writes() -> None:
    from neos.coding.repositories.projection_repository import TOOL_RISK_EVENT_TYPES
    from neos.jev.gate import JEV_RISK_SCORED, JEV_UNAVAILABLE

    assert set(TOOL_RISK_EVENT_TYPES) == {JEV_RISK_SCORED, JEV_UNAVAILABLE}


def _refusal_repository(refusal):
    from dataclasses import replace

    class RefusalRepository(ProjectionFixtureRepository):
        async def get_owned_snapshot(self, task_id: str, owner_id: str):
            rows = await super().get_owned_snapshot(task_id, owner_id)
            return replace(rows, refusal=refusal)

    return RefusalRepository(head_seq=14)


@pytest.mark.no_db
async def test_snapshot_carries_a_refusal_on_the_latest_run() -> None:
    """A refused run fails and is never retried, so the refusal is the last
    thing the user is told -- a refresh must not erase it.
    """
    from neos.coding.repositories.projection_repository import CodingRefusalRow

    payload = {"stop_reason": "refusal", "stop_category": "cyber"}
    snapshot = await CodingSnapshotService(
        _refusal_repository(CodingRefusalRow("cr_2", 13, payload))
    ).get_owned("ct_1", "u1")

    assert snapshot is not None
    assert snapshot.refusal is not None
    assert snapshot.refusal.run_id == "cr_2"
    assert snapshot.refusal.seq == 13
    assert snapshot.refusal.payload == payload


@pytest.mark.no_db
async def test_snapshot_drops_a_refusal_a_newer_run_has_cleared() -> None:
    """Live, `run.started` clears the refusal. A snapshot taken after a newer
    run started must agree, or a reconnect resurrects the banner.
    """
    from neos.coding.repositories.projection_repository import CodingRefusalRow

    snapshot = await CodingSnapshotService(
        _refusal_repository(CodingRefusalRow("cr_1", 7, {"stop_reason": "refusal"}))
    ).get_owned("ct_1", "u1")

    assert snapshot is not None
    assert snapshot.refusal is None


@pytest.mark.no_db
async def test_snapshot_without_a_refusal_has_none() -> None:
    snapshot = await CodingSnapshotService(_refusal_repository(None)).get_owned(
        "ct_1", "u1"
    )

    assert snapshot is not None
    assert snapshot.refusal is None


@pytest.mark.no_db
async def test_snapshot_carries_child_events_in_seq_order() -> None:
    """A child that ended after the checkpoint lives only in the ledger. The
    snapshot must carry its events as written, oldest first, so the client can
    fold them after `active_children` and let the terminal event win.
    """
    from dataclasses import replace

    from neos.coding.repositories.projection_repository import CodingChildEventRow

    started = {"run_id": "sa_1", "spec": "explore", "status": "pending"}
    stalled = {"run_id": "sa_1", "status": "failed", "error_code": "stalled"}
    done = {"run_id": "sa_2", "turn_count": 3, "tool_count": 2}

    class ChildRepository(ProjectionFixtureRepository):
        async def get_owned_snapshot(self, task_id: str, owner_id: str):
            rows = await super().get_owned_snapshot(task_id, owner_id)
            return replace(
                rows,
                child_events=(
                    CodingChildEventRow("subagent.failed", 12, stalled),
                    CodingChildEventRow("subagent.started", 5, started),
                    CodingChildEventRow("subagent.completed", 9, done),
                ),
            )

    snapshot = await CodingSnapshotService(ChildRepository(head_seq=14)).get_owned(
        "ct_1", "u1"
    )

    assert snapshot is not None
    assert [(e.type, e.seq) for e in snapshot.child_events] == [
        ("subagent.started", 5),
        ("subagent.completed", 9),
        ("subagent.failed", 12),
    ]
    assert snapshot.child_events[0].payload == started
    assert snapshot.child_events[2].payload == stalled


def test_projection_reads_the_kinds_the_parent_sink_forwards() -> None:
    from neos.coding.repositories.projection_repository import CHILD_EVENT_TYPES
    from neos.coding.runtime import _PARENT_SINK_EVENTS

    assert set(CHILD_EVENT_TYPES) == set(_PARENT_SINK_EVENTS)
