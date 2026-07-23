from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.application.workspace_service import CodingWorkspaceService
from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditCommit,
    WorkspaceEditConflict,
    WorkspaceEditStatus,
)
from neos.coding.sandbox.base import SandboxStateConflict
from neos.coding.sandbox.bindings import BoundSandboxSession, SandboxBinding


NOW = datetime(2026, 7, 23, tzinfo=UTC)


class Tasks:
    async def get_owned(self, task_id: str, owner_id: str):
        if task_id != "ct_1" or owner_id != "u1":
            return None
        return CodingTask(
            task_id=task_id,
            owner_id=owner_id,
            prompt="work",
            status=CodingTaskStatus.RUNNING,
            version=1,
            last_seq=0,
            created_at=NOW,
            updated_at=NOW,
        )


class Runs:
    async def latest_run(self, task_id: str):
        if task_id != "ct_1":
            return None
        return CodingRun(
            run_id="cr_1",
            task_id=task_id,
            attempt=1,
            status=CodingRunStatus.RUNNING,
            resume_from_checkpoint_id=None,
            started_at=NOW,
        )


class Session:
    def __init__(self, revision: int = 12) -> None:
        self.revision = revision
        self.write_count = 0
        self.files: dict[str, bytes] = {}
        self.fail_after_write = False

    async def write_file_if_revision(
        self, path: str, content: bytes, *, expected_revision: int
    ) -> int:
        if self.revision != expected_revision:
            raise SandboxStateConflict("workspace_revision_conflict")
        self.write_count += 1
        self.files[path] = content
        self.revision += 1
        if self.fail_after_write:
            raise SandboxStateConflict("workspace_write_outcome_unknown")
        return self.revision

    async def workspace_revision(self) -> int:
        return self.revision

    async def read_file(self, path: str) -> bytes:
        return self.files[path]


class Bindings:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def open_existing_admin(self, task_id: str):
        return BoundSandboxSession(
            SandboxBinding(
                task_id=task_id,
                run_id="cr_1",
                sandbox_id="sb_1",
                provider="memory",
                image_digest=None,
                workspace_revision=str(self.session.revision),
                latest_snapshot_id=None,
                health_state="healthy",
                mutation_count=0,
                version=1,
            ),
            self.session,
        )


class Edits:
    def __init__(self) -> None:
        self.values: dict[str, CodingWorkspaceEdit] = {}

    async def prepare_edit(self, **values):
        existing = self.values.get(values["edit_id"])
        if existing is not None:
            if (
                existing.task_id,
                existing.run_id,
                existing.path,
                existing.base_revision,
                existing.content_digest,
                existing.content_bytes,
            ) != (
                values["task_id"],
                values["run_id"],
                values["path"],
                values["base_revision"],
                values["digest"],
                values["content_bytes"],
            ):
                raise WorkspaceEditConflict("workspace_edit_exists")
            return WorkspaceEditCommit(existing, None, False)
        edit = CodingWorkspaceEdit(
            edit_id=values["edit_id"],
            task_id=values["task_id"],
            run_id=values["run_id"],
            path=values["path"],
            base_revision=values["base_revision"],
            resulting_revision=None,
            status=WorkspaceEditStatus.PREPARED,
            content_digest=values["digest"],
            content_bytes=values["content_bytes"],
            created_at=values["now"],
            committed_at=None,
            applied_checkpoint_id=None,
        )
        self.values[edit.edit_id] = edit
        return WorkspaceEditCommit(edit, None, True)

    async def commit_edit(self, *, edit_id, resulting_revision, now):
        edit = replace(
            self.values[edit_id],
            status=WorkspaceEditStatus.COMMITTED,
            resulting_revision=resulting_revision,
            committed_at=now,
        )
        self.values[edit_id] = edit
        return WorkspaceEditCommit(edit, None, True)

    async def mark_reconcile_required(self, *, edit_id, now):
        edit = replace(
            self.values[edit_id],
            status=WorkspaceEditStatus.RECONCILE_REQUIRED,
        )
        self.values[edit_id] = edit
        return edit

    async def list_reconcile_required(self, *, limit):
        return tuple(
            edit
            for edit in self.values.values()
            if edit.status is WorkspaceEditStatus.RECONCILE_REQUIRED
        )[:limit]


def make_service(session: Session):
    edits = Edits()
    return (
        CodingWorkspaceService(
            tasks=Tasks(),
            runs=Runs(),
            bindings=Bindings(session),
            edits=edits,
            max_file_bytes=128,
            clock=lambda: NOW,
        ),
        edits,
    )


async def test_duplicate_edit_id_reuses_committed_result() -> None:
    session = Session()
    service, _ = make_service(session)

    first = await service.save_file(
        task_id="ct_1",
        owner_id="u1",
        edit_id="cwe_1",
        path="src/app.py",
        base_revision="12",
        content="return 1\n",
    )
    second = await service.save_file(
        task_id="ct_1",
        owner_id="u1",
        edit_id="cwe_1",
        path="src/app.py",
        base_revision="12",
        content="return 1\n",
    )

    assert second == first
    assert first.resulting_revision == "13"
    assert session.write_count == 1


async def test_stale_revision_preserves_workspace() -> None:
    session = Session()
    service, _ = make_service(session)

    with pytest.raises(
        WorkspaceEditConflict, match="workspace_revision_conflict"
    ):
        await service.save_file(
            task_id="ct_1",
            owner_id="u1",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="11",
            content="return 1\n",
        )

    assert session.write_count == 0
    assert session.files == {}


async def test_ambiguous_write_is_marked_for_reconciliation() -> None:
    session = Session()
    session.fail_after_write = True
    service, edits = make_service(session)

    with pytest.raises(
        WorkspaceEditConflict, match="workspace_edit_reconcile_required"
    ):
        await service.save_file(
            task_id="ct_1",
            owner_id="u1",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="12",
            content="return 1\n",
        )

    assert edits.values["cwe_1"].status is WorkspaceEditStatus.RECONCILE_REQUIRED


async def test_reconciliation_commits_only_exact_revision_and_digest() -> None:
    session = Session()
    session.fail_after_write = True
    service, edits = make_service(session)
    with pytest.raises(WorkspaceEditConflict):
        await service.save_file(
            task_id="ct_1",
            owner_id="u1",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="12",
            content="return 1\n",
        )
    session.fail_after_write = False

    reconciled = await service.reconcile_edits(limit=10)

    assert [result.edit_id for result in reconciled] == ["cwe_1"]
    assert edits.values["cwe_1"].status is WorkspaceEditStatus.COMMITTED
    assert edits.values["cwe_1"].resulting_revision == "13"


async def test_reconciliation_leaves_changed_file_unresolved() -> None:
    session = Session()
    session.fail_after_write = True
    service, edits = make_service(session)
    with pytest.raises(WorkspaceEditConflict):
        await service.save_file(
            task_id="ct_1",
            owner_id="u1",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="12",
            content="return 1\n",
        )
    session.files["src/app.py"] = b"different"
    session.fail_after_write = False

    assert await service.reconcile_edits(limit=10) == ()
    assert (
        edits.values["cwe_1"].status
        is WorkspaceEditStatus.RECONCILE_REQUIRED
    )


async def test_foreign_task_is_hidden_before_binding_access() -> None:
    session = Session()
    service, _ = make_service(session)

    with pytest.raises(WorkspaceEditConflict, match="workspace_not_found"):
        await service.save_file(
            task_id="ct_1",
            owner_id="u2",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="12",
            content="return 1\n",
        )

    assert session.write_count == 0


async def test_file_limit_is_checked_before_preparing_intent() -> None:
    service, edits = make_service(Session())

    with pytest.raises(WorkspaceEditConflict, match="workspace_file_too_large"):
        await service.save_file(
            task_id="ct_1",
            owner_id="u1",
            edit_id="cwe_1",
            path="src/app.py",
            base_revision="12",
            content="x" * 129,
        )

    assert edits.values == {}
