from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable, Literal, Protocol

from neos.coding.domain.phases import CodingRunStatus
from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditCommit,
    WorkspaceEditConflict,
    WorkspaceEditStatus,
)
from neos.coding.sandbox.base import SandboxStateConflict
from neos.coding.sandbox.base import FileEntry
from neos.coding.sandbox.bindings import (
    BoundSandboxSession,
    SandboxBindingService,
)


class OwnedTaskRepository(Protocol):
    async def get_owned(self, task_id: str, owner_id: str): ...


class LatestRunRepository(Protocol):
    async def latest_run(self, task_id: str): ...


class WorkspaceEditRepository(Protocol):
    async def prepare_edit(self, **values) -> WorkspaceEditCommit: ...

    async def commit_edit(
        self, *, edit_id: str, resulting_revision: str, now: datetime
    ) -> WorkspaceEditCommit: ...

    async def mark_reconcile_required(
        self, *, edit_id: str, now: datetime
    ) -> CodingWorkspaceEdit: ...

    async def list_reconcile_required(
        self, *, limit: int
    ) -> tuple[CodingWorkspaceEdit, ...]: ...


@dataclass(frozen=True, slots=True)
class WorkspaceFileSaveResult:
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str
    status: Literal["pending_agent_sync"] = "pending_agent_sync"


@dataclass(frozen=True, slots=True)
class WorkspaceTreeResult:
    entries: tuple[FileEntry, ...]
    workspace_revision: str


@dataclass(frozen=True, slots=True)
class WorkspaceFileResult:
    path: str
    content: str | None
    binary: bool
    size: int
    workspace_revision: str


@dataclass(frozen=True, slots=True)
class WorkspaceDiffResult:
    content: str
    truncated: bool
    workspace_revision: str


class CodingWorkspaceService:
    def __init__(
        self,
        *,
        tasks: OwnedTaskRepository,
        runs: LatestRunRepository,
        bindings: SandboxBindingService,
        edits: WorkspaceEditRepository,
        max_file_bytes: int,
        max_tree_entries: int = 5_000,
        max_diff_bytes: int = 2 * 1024 * 1024,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if min(max_file_bytes, max_tree_entries, max_diff_bytes) < 1:
            raise ValueError("workspace limits must be positive")
        self._tasks = tasks
        self._runs = runs
        self._bindings = bindings
        self._edits = edits
        self._max_file_bytes = max_file_bytes
        self._max_tree_entries = max_tree_entries
        self._max_diff_bytes = max_diff_bytes
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_tree(
        self,
        *,
        task_id: str,
        owner_id: str,
        path: str = ".",
    ) -> WorkspaceTreeResult:
        bound = await self._owned_binding(task_id, owner_id)
        entries = tuple(
            sorted(
                await bound.session.list_tree(path),
                key=lambda entry: entry.path,
            )
        )
        if len(entries) > self._max_tree_entries:
            raise WorkspaceEditConflict("workspace_tree_too_large")
        return WorkspaceTreeResult(
            entries=entries,
            workspace_revision=str(
                await bound.session.workspace_revision()
            ),
        )

    async def read_file(
        self,
        *,
        task_id: str,
        owner_id: str,
        path: str,
    ) -> WorkspaceFileResult:
        bound = await self._owned_binding(task_id, owner_id)
        entry = await bound.session.stat(path)
        if entry.kind != "file":
            raise WorkspaceEditConflict("workspace_path_is_not_file")
        if entry.size > self._max_file_bytes:
            raise WorkspaceEditConflict("workspace_file_too_large")
        raw = await bound.session.read_file(path)
        try:
            content = raw.decode("utf-8")
            binary = False
        except UnicodeDecodeError:
            content = None
            binary = True
        return WorkspaceFileResult(
            path=entry.path,
            content=content,
            binary=binary,
            size=entry.size,
            workspace_revision=str(
                await bound.session.workspace_revision()
            ),
        )

    async def git_diff(
        self,
        *,
        task_id: str,
        owner_id: str,
        staged: bool = False,
    ) -> WorkspaceDiffResult:
        bound = await self._owned_binding(task_id, owner_id)
        result = await bound.session.git_diff(staged=staged)
        raw = result.stdout
        truncated = len(raw) > self._max_diff_bytes
        if truncated:
            raw = raw[: self._max_diff_bytes]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            if not truncated:
                raise WorkspaceEditConflict(
                    "workspace_diff_not_utf8"
                ) from None
            content = raw.decode("utf-8", errors="ignore")
        return WorkspaceDiffResult(
            content=content,
            truncated=truncated or result.stdout_truncated,
            workspace_revision=str(
                await bound.session.workspace_revision()
            ),
        )

    async def save_file(
        self,
        *,
        task_id: str,
        owner_id: str,
        edit_id: str,
        path: str,
        base_revision: str,
        content: str,
    ) -> WorkspaceFileSaveResult:
        encoded = content.encode("utf-8")
        if len(encoded) > self._max_file_bytes:
            raise WorkspaceEditConflict("workspace_file_too_large")
        try:
            expected_revision = int(base_revision)
        except ValueError as error:
            raise WorkspaceEditConflict("workspace_revision_invalid") from error
        bound = await self._owned_binding(task_id, owner_id)
        prepared = await self._edits.prepare_edit(
            task_id=task_id,
            run_id=bound.binding.run_id,
            edit_id=edit_id,
            path=path,
            base_revision=base_revision,
            digest=self._digest(encoded),
            content_bytes=len(encoded),
            now=self._clock(),
        )
        if prepared.edit.status is WorkspaceEditStatus.COMMITTED:
            return self._save_result(prepared.edit)
        if prepared.edit.status is WorkspaceEditStatus.RECONCILE_REQUIRED:
            raise WorkspaceEditConflict("workspace_edit_reconcile_required")
        try:
            revision = await bound.session.write_file_if_revision(
                path,
                encoded,
                expected_revision=expected_revision,
            )
        except SandboxStateConflict as error:
            if str(error) == "workspace_revision_conflict":
                raise WorkspaceEditConflict(
                    "workspace_revision_conflict"
                ) from error
            await self._edits.mark_reconcile_required(
                edit_id=edit_id,
                now=self._clock(),
            )
            raise WorkspaceEditConflict(
                "workspace_edit_reconcile_required"
            ) from error
        committed = await self._edits.commit_edit(
            edit_id=edit_id,
            resulting_revision=str(revision),
            now=self._clock(),
        )
        return self._save_result(committed.edit)

    async def reconcile_edits(
        self, *, limit: int
    ) -> tuple[WorkspaceFileSaveResult, ...]:
        if limit < 1:
            raise ValueError("reconciliation limit must be positive")
        reconciled: list[WorkspaceFileSaveResult] = []
        pending = await self._edits.list_reconcile_required(limit=limit)
        for edit in pending:
            try:
                bound = await self._bindings.open_existing_admin(edit.task_id)
                if bound.binding.run_id != edit.run_id:
                    continue
                revision = await bound.session.workspace_revision()
                if revision != int(edit.base_revision) + 1:
                    continue
                content = await bound.session.read_file(edit.path)
                if self._digest(content) != edit.content_digest:
                    continue
                committed = await self._edits.commit_edit(
                    edit_id=edit.edit_id,
                    resulting_revision=str(revision),
                    now=self._clock(),
                )
            except (KeyError, ValueError, SandboxStateConflict):
                continue
            reconciled.append(self._save_result(committed.edit))
        return tuple(reconciled)

    async def _owned_binding(
        self, task_id: str, owner_id: str
    ) -> BoundSandboxSession:
        if await self._tasks.get_owned(task_id, owner_id) is None:
            raise WorkspaceEditConflict("workspace_not_found")
        run = await self._runs.latest_run(task_id)
        if run is None or run.status is not CodingRunStatus.RUNNING:
            raise WorkspaceEditConflict("workspace_run_not_running")
        bound = await self._bindings.open_existing_admin(task_id)
        if bound.binding.run_id != run.run_id:
            raise WorkspaceEditConflict("workspace_run_changed")
        return bound

    @staticmethod
    def _digest(content: bytes) -> str:
        return f"sha256:{sha256(content).hexdigest()}"

    @staticmethod
    def _save_result(edit: CodingWorkspaceEdit) -> WorkspaceFileSaveResult:
        if edit.resulting_revision is None:
            raise WorkspaceEditConflict("workspace_edit_reconcile_required")
        return WorkspaceFileSaveResult(
            edit_id=edit.edit_id,
            path=edit.path,
            base_revision=edit.base_revision,
            resulting_revision=edit.resulting_revision,
        )
