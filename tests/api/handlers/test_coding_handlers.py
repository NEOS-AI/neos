import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.coding_handlers import (
    get_coding_approval_service,
    get_coding_run_service,
    get_coding_service,
    get_coding_snapshot_service,
    get_ws_ticket_store,
    router,
)
from neos.coding.domain.approvals import ApprovalConflict, ApprovalNotFound
from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.auth.ws_tickets import InMemoryWsTicketStore
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from tests.coding.fakes import InMemoryCodingRunRepository


def make_client(user_id="u1"):
    app = FastAPI()
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id=user_id
    )
    app.dependency_overrides[get_coding_service] = lambda: service

    class SnapshotAdapter:
        async def get_owned(self, task_id, owner_id):
            snapshot = await service.snapshot(task_id, owner_id)
            if snapshot is None:
                return None
            return SimpleNamespace(
                task=snapshot.task,
                active_run=None,
                phases=(),
                tools=(),
                approvals=(),
                todos=(),
                workspace=SimpleNamespace(
                    revision="uninitialized", git_head=None, changed_files=()
                ),
                latest_checkpoint=None,
                head_seq=snapshot.head_seq,
                connection_basis="checkpoint",
            )

    service.projection_snapshots = SnapshotAdapter()
    app.dependency_overrides[get_coding_snapshot_service] = (
        lambda: service.projection_snapshots
    )
    runs = CodingRunService(
        tasks=service.tasks,
        runs=InMemoryCodingRunRepository(),
        events=service.events,
        interrupter=InProcessRunInterrupter(),
    )
    app.dependency_overrides[get_coding_run_service] = lambda: runs
    return TestClient(app), service


def test_owner_can_resolve_coding_approval() -> None:
    client, _ = make_client("owner")

    class Approvals:
        async def resolve(self, **kwargs):
            assert kwargs == {
                "task_id": "ct_1", "approval_id": "ca_1",
                "owner_id": "owner", "decision": kwargs["decision"],
            }
            return SimpleNamespace(approval=SimpleNamespace(
                approval_id="ca_1", tool_name="write_file.v1",
                risk=SimpleNamespace(value="workspace_write"), status=SimpleNamespace(value="approved"),
                requested_at=datetime(2026, 7, 21, tzinfo=UTC),
                expires_at=datetime(2026, 7, 21, 0, 15, tzinfo=UTC),
                display_summary={"path": "a.py"},
            ))

    client.app.dependency_overrides[get_coding_approval_service] = Approvals
    response = client.post(
        "/api/v1/coding/tasks/ct_1/approvals/ca_1", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["display_summary"] == {"path": "a.py"}


def test_approval_not_found_and_conflict_are_sanitized() -> None:
    client, _ = make_client()

    class Approvals:
        async def resolve(self, **kwargs):
            if kwargs["approval_id"] == "missing":
                raise ApprovalNotFound
            raise ApprovalConflict("already_resolved")

    client.app.dependency_overrides[get_coding_approval_service] = Approvals
    missing = client.post(
        "/api/v1/coding/tasks/ct_1/approvals/missing", json={"decision": "deny"}
    )
    conflict = client.post(
        "/api/v1/coding/tasks/ct_1/approvals/stale", json={"decision": "deny"}
    )
    assert missing.status_code == 404
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Coding approval cannot be resolved"}


def test_create_task_returns_202_and_replayable_created_event() -> None:
    client, _ = make_client()

    created = client.post("/api/v1/coding/tasks", json={"prompt": "Fix it"})

    assert created.status_code == 202
    task_id = created.json()["task_id"]
    replay = client.get(f"/api/v1/coding/tasks/{task_id}/events?after_seq=0")
    assert replay.status_code == 200
    assert replay.json()["events"][0]["type"] == "task.created"


def test_event_replay_exposes_checkpoint_identity() -> None:
    client, service = make_client()
    task_id = client.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    asyncio.run(
        service.events.append(
            task_id=task_id,
            event_type="checkpoint.created",
            payload={},
            now=datetime(2026, 7, 19, tzinfo=UTC),
            checkpoint_id="cc_1",
        )
    )

    replay = client.get(f"/api/v1/coding/tasks/{task_id}/events?after_seq=1")

    assert replay.json()["events"][0]["checkpoint_id"] == "cc_1"


def test_foreign_task_is_hidden_as_404() -> None:
    owner, service = make_client("owner")
    task_id = owner.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    foreign, _ = make_client("foreign")
    foreign.app.dependency_overrides[get_coding_service] = lambda: service
    foreign.app.dependency_overrides[get_coding_snapshot_service] = (
        lambda: service.projection_snapshots
    )

    response = foreign.get(f"/api/v1/coding/tasks/{task_id}/snapshot")

    assert response.status_code == 404


def test_owner_can_issue_task_bound_websocket_ticket() -> None:
    client, _ = make_client("u1")
    client.app.dependency_overrides[get_ws_ticket_store] = (
        lambda: InMemoryWsTicketStore()
    )
    task_id = client.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]

    response = client.post(f"/api/v1/coding/tasks/{task_id}/ws-ticket")

    assert response.status_code == 201
    assert response.json()["ticket"].startswith("cwt_")
    assert response.json()["expires_in"] == 30


def test_foreign_user_cannot_issue_websocket_ticket() -> None:
    owner, service = make_client("owner")
    task_id = owner.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    foreign, _ = make_client("foreign")
    foreign.app.dependency_overrides[get_coding_service] = lambda: service

    response = foreign.post(f"/api/v1/coding/tasks/{task_id}/ws-ticket")

    assert response.status_code == 404


def test_foreign_user_cannot_steer_coding_task() -> None:
    owner, _ = make_client("owner")
    task_id = owner.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    foreign, _ = make_client("foreign")

    response = foreign.post(
        f"/api/v1/coding/tasks/{task_id}/steer",
        json={"instruction": "exfiltrate", "mode": "interrupt_now"},
    )

    assert response.status_code == 404


def test_snapshot_returns_phase_and_checkpoint_state() -> None:
    client, _ = make_client("u1")
    now = datetime(2026, 7, 19, tzinfo=UTC)

    class SnapshotService:
        async def get_owned(self, task_id, owner_id):
            assert owner_id == "u1"
            return SimpleNamespace(
                task=SimpleNamespace(
                    task_id=task_id,
                    status="running",
                    version=2,
                    last_seq=14,
                    created_at=now,
                    updated_at=now,
                ),
                active_run=SimpleNamespace(
                    run_id="cr_2",
                    attempt=2,
                    status="running",
                    resume_from_checkpoint_id="cc_10",
                ),
                phases=(
                    SimpleNamespace(
                        phase_id="phase_1",
                        run_id="cr_1",
                        kind="understand",
                        attempt=1,
                        status="completed",
                        started_at=now,
                        completed_at=now,
                    ),
                ),
                tools=(),
                approvals=(),
                todos=(),
                workspace=SimpleNamespace(
                    revision="rev_12", git_head=None, changed_files=("app.py",)
                ),
                latest_checkpoint=SimpleNamespace(
                    checkpoint_id="cc_12",
                    run_id="cr_2",
                    seq=12,
                    loop_state={"phase_index": 0},
                    workspace_revision="rev_12",
                    created_at=now,
                ),
                head_seq=14,
                connection_basis="checkpoint",
            )

    client.app.dependency_overrides[get_coding_snapshot_service] = SnapshotService

    response = client.get("/api/v1/coding/tasks/ct_1/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["head_seq"] == 14
    assert body["active_run"]["run_id"] == "cr_2"
    assert body["phases"][0]["kind"] == "understand"
    assert body["connection_basis"] == "checkpoint"
