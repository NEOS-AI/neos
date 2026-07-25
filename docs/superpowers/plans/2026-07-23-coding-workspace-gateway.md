# Coding Workspace Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an owner-scoped file/diff/watcher/interactive-PTY workspace dock whose explicit user edits are durably injected into the coding agent at the next safe point.

**Architecture:** A dedicated `CodingWorkspaceService` resolves the canonical sandbox binding and serves bounded REST operations while workspace WebSockets use stream-kind-bound one-time tickets. User writes use a durable intent/reconciliation protocol because the sandbox and PostgreSQL cannot share a transaction; committed edits are claimed and marked synced inside the existing fenced safe-point checkpoint transaction. The browser keeps agent projection, revision-keyed workspace queries, edit drafts, and PTY replay in separate stores.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/PostgreSQL, existing `SandboxProvider`/`SandboxBindingService`, Redis/in-memory tickets, Next.js 15, React 19, TypeScript, Node test runner, Docker opt-in integration tests.

## Global Constraints

- Work inline on the current `dev` branch; do not create a worktree unless the user changes execution mode.
- Preserve `.env.template` and the three unrelated untracked 2026-07-11 deep-analysis documents.
- Default file UX is read-only; editing requires an explicit `Edit` action and remains single-file.
- Never auto-merge or overwrite a stale revision.
- PTY input is an authenticated user action, not an agent tool approval.
- File content, terminal input/output, command values, paths, and actor identifiers must not appear in metric labels or general logs.
- Agent events, watcher events, and PTY output retain independent cursors and failure domains.
- WebSocket tickets are one-time, short-lived, and bound to task, owner, and stream kind.
- Tree, file, diff, watcher frame, PTY frame, edit batch, and replay buffers are bounded.
- `workspace.user_edit.applied` and `workspace.user_edit.synced` never contain file content or content digests.
- A committed edit is injected into model context exactly once through a fenced safe-point checkpoint.
- Use tests before implementation, run focused verification per task, and commit only that task's files.

---

### Task 1: Durable Workspace Edit Domain, Configuration, and Migration

**Files:**
- Create: `neos/coding/domain/workspace_edits.py`
- Create: `db/migrations/044_add_coding_workspace_edits.sql`
- Modify: `neos/config/schema.py`
- Modify: `config/neos.default.yaml`
- Create: `tests/coding/domain/test_workspace_edits.py`
- Create: `tests/coding/test_migration_044_contract.py`
- Modify: `tests/config/test_sandbox_config.py`

**Interfaces:**
- Consumes: existing task/run/checkpoint identities and `CodingEvent`.
- Produces: `WorkspaceEditStatus`, `CodingWorkspaceEdit`, `WorkspaceEditCommit`, `WorkspaceEditConflict`, and bounded workspace settings consumed by Tasks 2–8.

- [ ] **Step 1: Write failing domain and migration tests**

```python
from datetime import UTC, datetime
import pytest

from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditStatus,
)

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def test_workspace_edit_requires_a_valid_revision_transition() -> None:
    edit = CodingWorkspaceEdit(
        edit_id="cwe_1",
        task_id="ct_1",
        run_id="cr_1",
        path="src/app.py",
        base_revision="12",
        resulting_revision="13",
        status=WorkspaceEditStatus.COMMITTED,
        content_digest="sha256:abc",
        content_bytes=6,
        created_at=NOW,
        committed_at=NOW,
        applied_checkpoint_id=None,
    )
    assert edit.pending_agent_sync is True


def test_applied_edit_requires_checkpoint_identity() -> None:
    with pytest.raises(ValueError, match="applied checkpoint"):
        CodingWorkspaceEdit(
            edit_id="cwe_1", task_id="ct_1", run_id="cr_1",
            path="src/app.py", base_revision="12", resulting_revision="13",
            status=WorkspaceEditStatus.APPLIED,
            content_digest="sha256:abc", content_bytes=6,
            created_at=NOW, committed_at=NOW, applied_checkpoint_id=None,
        )
```

Migration contract:

```python
from pathlib import Path


def test_migration_044_has_idempotency_and_task_cleanup() -> None:
    sql = Path("db/migrations/044_add_coding_workspace_edits.sql").read_text()
    assert "edit_id TEXT PRIMARY KEY" in sql
    assert "REFERENCES coding_tasks(task_id) ON DELETE CASCADE" in sql
    assert "CHECK (status IN ('prepared', 'committed', 'reconcile_required', 'applied'))" in sql
    assert "idx_coding_workspace_edits_pending" in sql
```

- [ ] **Step 2: Run tests and confirm missing contracts**

Run:

```bash
.venv/bin/pytest -q tests/coding/domain/test_workspace_edits.py \
  tests/coding/test_migration_044_contract.py \
  tests/config/test_sandbox_config.py
```

Expected: import/migration/settings failures for workspace edit contracts.

- [ ] **Step 3: Implement immutable domain types**

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.domain.events import CodingEvent


class WorkspaceEditStatus(StrEnum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    RECONCILE_REQUIRED = "reconcile_required"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class CodingWorkspaceEdit:
    edit_id: str
    task_id: str
    run_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: WorkspaceEditStatus
    content_digest: str
    content_bytes: int
    created_at: datetime
    committed_at: datetime | None
    applied_checkpoint_id: str | None

    def __post_init__(self) -> None:
        if not all((self.edit_id, self.task_id, self.run_id, self.path)):
            raise ValueError("workspace edit identities are required")
        if self.content_bytes < 0:
            raise ValueError("workspace edit content bytes cannot be negative")
        if self.status is WorkspaceEditStatus.APPLIED and not self.applied_checkpoint_id:
            raise ValueError("applied checkpoint is required")

    @property
    def pending_agent_sync(self) -> bool:
        return self.status is WorkspaceEditStatus.COMMITTED


@dataclass(frozen=True, slots=True)
class WorkspaceEditCommit:
    edit: CodingWorkspaceEdit
    event: CodingEvent | None
    created: bool


class WorkspaceEditConflict(RuntimeError):
    pass
```

- [ ] **Step 4: Add migration and bounded settings**

Migration columns must match the domain type, use `BIGINT` for byte count,
index `(task_id, status, committed_at, edit_id)`, and retain no file body.

Add a `SandboxWorkspaceConfig` nested at `sandbox.workspace` so gateway
limits remain distinct from provider execution and replay limits:

```python
class SandboxWorkspaceConfig(StrictConfigModel):
    tree_max_entries: int = Field(default=5_000, gt=0, le=20_000)
    file_max_bytes: int = Field(default=1_048_576, gt=0)
    diff_max_bytes: int = Field(default=2_097_152, gt=0)
    edit_batch_size: int = Field(default=20, gt=0, le=100)
    ticket_ttl_seconds: int = Field(default=30, gt=0, le=300)
    pty_idle_ttl_seconds: int = Field(default=1_800, gt=0)
    pty_max_sessions: int = Field(default=3, gt=0, le=10)
```

Add `workspace: SandboxWorkspaceConfig` to `SandboxConfig`, mirror all
defaults under `sandbox.workspace` in `config/neos.default.yaml`, and assert
defaults plus invalid bounds in `tests/config/test_sandbox_config.py`.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/domain/test_workspace_edits.py \
  tests/coding/test_migration_044_contract.py \
  tests/config/test_sandbox_config.py
.venv/bin/ruff check neos/coding/domain/workspace_edits.py \
  tests/coding/domain/test_workspace_edits.py \
  tests/coding/test_migration_044_contract.py
git diff --check
git add neos/coding/domain/workspace_edits.py \
  db/migrations/044_add_coding_workspace_edits.sql neos/config/schema.py \
  config/neos.default.yaml tests/coding/domain/test_workspace_edits.py \
  tests/coding/test_migration_044_contract.py \
  tests/config/test_sandbox_config.py
git commit -m "feat(coding): define durable workspace edits"
```

Expected: focused tests and Ruff pass.

### Task 2: Intent-Based User Edit Mutation and Reconciliation

**Files:**
- Create: `neos/coding/repositories/workspace_edit_repository.py`
- Create: `neos/coding/application/workspace_service.py`
- Modify: `neos/coding/sandbox/base.py`
- Modify: `neos/coding/sandbox/memory.py`
- Modify: `neos/coding/sandbox/docker.py`
- Modify: `neos/coding/sandbox/bindings.py`
- Create: `tests/coding/repositories/test_workspace_edit_repository.py`
- Create: `tests/coding/application/test_workspace_service.py`
- Modify: `tests/coding/sandbox/conformance.py`

**Interfaces:**
- Consumes: Task 1 domain/settings, `SandboxBindingService`, and sandbox path policy.
- Produces:
  - `prepare_edit(*, task_id, run_id, edit_id, path, base_revision, digest, content_bytes, now) -> WorkspaceEditCommit`
  - `commit_edit(*, edit_id, resulting_revision, now) -> WorkspaceEditCommit`
  - `mark_reconcile_required(*, edit_id, now) -> CodingWorkspaceEdit`
  - `CodingWorkspaceService.save_file(...) -> WorkspaceFileSaveResult`
  - `SandboxBindingService.open_existing_admin(task_id) -> BoundSandboxSession`
  - conditional `SandboxSession.write_file_if_revision(...) -> int`

- [ ] **Step 1: Write failing repository and service tests**

```python
async def test_duplicate_edit_id_reuses_committed_result() -> None:
    first = await service.save_file(
        task_id="ct_1", owner_id="u1", edit_id="cwe_1",
        path="src/app.py", base_revision="12", content="return 1\n",
    )
    second = await service.save_file(
        task_id="ct_1", owner_id="u1", edit_id="cwe_1",
        path="src/app.py", base_revision="12", content="return 1\n",
    )
    assert second == first
    assert session.write_count == 1


async def test_stale_revision_preserves_workspace() -> None:
    with pytest.raises(
        WorkspaceEditConflict, match="workspace_revision_conflict"
    ):
        await service.save_file(
            task_id="ct_1", owner_id="u1", edit_id="cwe_1",
            path="src/app.py", base_revision="11", content="return 1\n",
        )
    assert session.write_count == 0
```

Repository SQL test must assert prepared intent commits before any sandbox
write, duplicate identity is locked, and event/outbox are inserted only by
`commit_edit`.

- [ ] **Step 2: Run focused tests and confirm missing service/repository**

```bash
.venv/bin/pytest -q \
  tests/coding/repositories/test_workspace_edit_repository.py \
  tests/coding/application/test_workspace_service.py \
  tests/coding/sandbox/conformance.py
```

Expected: missing import/method failures.

- [ ] **Step 3: Add conditional sandbox write**

Extend the protocol:

```python
async def write_file_if_revision(
    self,
    path: str,
    content: bytes,
    *,
    expected_revision: int,
) -> int: ...
```

Memory and Docker implementations must lock the session mutation boundary,
compare `workspace_revision()`, raise
`SandboxStateConflict("workspace_revision_conflict")` before writing on
mismatch, then return the incremented revision. Add the same conformance test
for both providers.

- [ ] **Step 4: Implement fenced repository transitions**

`prepare_edit` verifies the owner-scoped task and canonical running run,
returns an identical existing edit only when task/run/path/base revision and
digest match, otherwise raises `WorkspaceEditConflict("workspace_edit_exists")`.

`commit_edit` locks the prepared/reconcile row, allocates one task sequence,
sets `committed`, and inserts a `workspace.user_edit.applied` event plus its
outbox row:

```python
payload = {
    "edit_id": edit.edit_id,
    "path": edit.path,
    "base_revision": edit.base_revision,
    "resulting_revision": resulting_revision,
    "status": "pending_agent_sync",
}
```

Use the existing coding event/outbox schema and wake only after transaction
exit.

- [ ] **Step 5: Implement save orchestration and ambiguous outcome handling**

Define the public application result explicitly:

```python
@dataclass(frozen=True, slots=True)
class WorkspaceFileSaveResult:
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str
    status: Literal["pending_agent_sync"]
```

`CodingWorkspaceService` receives the existing task and run repository
protocols. `_owned_binding(task_id, owner_id)` must:

1. call `tasks.get_owned(task_id, owner_id)` and return not-found for foreign
   or missing tasks;
2. call `runs.latest_run(task_id)` and require the canonical run to be
   running;
3. call `bindings.open_existing_admin(task_id)`;
4. require `bound.binding.run_id == run.run_id`, otherwise return
   `workspace_run_changed` and let the client refetch.

`open_existing_admin` is deliberately non-creating: it loads the durable
binding, verifies image/provider/owner identity and running health, and opens
the existing session. It may use the existing admin resume operation, but it
must not create, restore, rebind, or advance a run without an execution
lease. This keeps browser reads and writes outside worker fencing while the
owner check remains in the application service.

```python
async def save_file(self, *, task_id, owner_id, edit_id, path,
                    base_revision, content) -> WorkspaceFileSaveResult:
    encoded = content.encode("utf-8")
    if len(encoded) > self._max_file_bytes:
        raise WorkspaceEditConflict("workspace_file_too_large")
    bound = await self._owned_binding(task_id, owner_id)
    prepared = await self._edits.prepare_edit(
        task_id=task_id, run_id=bound.binding.run_id, edit_id=edit_id,
        path=path, base_revision=base_revision,
        digest=self._digest(encoded), content_bytes=len(encoded),
        now=self._clock(),
    )
    if prepared.edit.status is WorkspaceEditStatus.COMMITTED:
        return self._save_result(prepared.edit)
    try:
        revision = await bound.session.write_file_if_revision(
            path, encoded, expected_revision=int(base_revision)
        )
    except SandboxStateConflict as error:
        if str(error) == "workspace_revision_conflict":
            raise WorkspaceEditConflict("workspace_revision_conflict") from error
        await self._edits.mark_reconcile_required(
            edit_id=edit_id, now=self._clock()
        )
        raise WorkspaceEditConflict(
            "workspace_edit_reconcile_required"
        ) from error
    committed = await self._edits.commit_edit(
        edit_id=edit_id, resulting_revision=str(revision), now=self._clock()
    )
    return self._save_result(committed.edit)
```

Add `reconcile_edits(limit, now)` that resolves binding/session, compares
revision and digest, completes only exact matches, and otherwise leaves the
row reconcile-required.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest -q \
  tests/coding/repositories/test_workspace_edit_repository.py \
  tests/coding/application/test_workspace_service.py \
  tests/coding/sandbox/test_memory.py \
  tests/coding/sandbox/test_docker_provider.py
.venv/bin/ruff check neos/coding/repositories/workspace_edit_repository.py \
  neos/coding/application/workspace_service.py tests/coding
git diff --check
git add neos/coding/repositories/workspace_edit_repository.py \
  neos/coding/application/workspace_service.py neos/coding/sandbox/base.py \
  neos/coding/sandbox/memory.py neos/coding/sandbox/docker.py \
  neos/coding/sandbox/bindings.py \
  tests/coding/repositories/test_workspace_edit_repository.py \
  tests/coding/application/test_workspace_service.py \
  tests/coding/sandbox/conformance.py
git commit -m "feat(coding): persist user workspace edits"
```

### Task 3: Exactly-Once Safe-Point Edit Injection

**Files:**
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/application/run_service.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `neos/coding/loop/anthropic.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/application/test_workspace_edit_safe_point.py`
- Modify: `tests/coding/loop/test_anthropic_loop.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`

**Interfaces:**
- Consumes: committed Task 2 edits and existing execution lease/checkpoint.
- Produces:
  - `claim_workspace_edits_at_safe_point(*, lease, checkpoint, limit, now) -> WorkspaceEditApplication | None`
  - `LoopInput.workspace_edits: tuple[WorkspaceEditContext, ...]`
  - atomic `workspace.user_edit.synced` event and `applied_checkpoint_id`.

- [ ] **Step 1: Write failing safe-point tests**

```python
async def test_committed_edits_are_applied_once_with_checkpoint() -> None:
    first = await runs.claim_workspace_edits_at_safe_point(
        lease=lease, checkpoint=checkpoint, limit=20, now=NOW
    )
    second = await runs.claim_workspace_edits_at_safe_point(
        lease=lease, checkpoint=first.checkpoint, limit=20, now=NOW
    )
    assert [item.path for item in first.edits] == ["src/a.py", "src/b.py"]
    assert second is None
    assert all(
        item.applied_checkpoint_id == first.checkpoint.checkpoint_id
        for item in repository.workspace_edits.values()
    )
```

Also test stale lease rejection, batch limit, ordering by resulting revision
then edit identity, event sanitization, and replacement worker non-duplication.

- [ ] **Step 2: Run tests and confirm protocol is absent**

```bash
.venv/bin/pytest -q \
  tests/coding/application/test_workspace_edit_safe_point.py \
  tests/coding/loop/test_anthropic_loop.py
```

Expected: missing safe-point method/context failures.

- [ ] **Step 3: Add context/application types**

```python
@dataclass(frozen=True, slots=True)
class WorkspaceEditContext:
    edit_id: str
    path: str
    resulting_revision: str


@dataclass(frozen=True, slots=True)
class WorkspaceEditApplication:
    edits: tuple[CodingWorkspaceEdit, ...]
    checkpoint: CodingCheckpoint
    events: tuple[CodingEvent, ...]
```

Add `workspace_edits: tuple[WorkspaceEditContext, ...] = ()` to `LoopInput`.

- [ ] **Step 4: Implement atomic PostgreSQL claim**

Inside one transaction:

1. validate the lease and lock canonical running run;
2. select committed, unapplied rows using
   `FOR UPDATE SKIP LOCKED LIMIT :limit`;
3. allocate one task sequence per claimed edit in deterministic row order;
4. copy existing loop state and add a bounded `pending_workspace_edits` list;
5. insert one checkpoint whose sequence is the final allocated event sequence;
6. update all claimed rows to applied with the checkpoint identity;
7. insert one `workspace.user_edit.synced` event and matching outbox per edit,
   using the corresponding allocated sequence.

The checkpoint and final event intentionally share the final sequence, as
existing checkpoints and their public events occupy separate tables. No
sequence is allocated and no checkpoint is written when the claim is empty.
The entire claim, checkpoint, edit update, events, outbox, and task
`last_seq` advancement remains one fenced database transaction.

The public payload is:

```python
{
    "edit_id": edit.edit_id,
    "path": edit.path,
    "resulting_revision": edit.resulting_revision,
    "status": "agent_synced",
    "applied_checkpoint_id": checkpoint.checkpoint_id,
}
```

- [ ] **Step 5: Wire run service and model request**

In `advance_one_safe_point`, claim workspace edits after steering application
and before constructing `LoopInput`. Replace `checkpoint` with the returned
checkpoint and pass contexts to the loop.

The Anthropic loop adds one canonical user message:

```python
{
    "role": "user",
    "content": [{
        "type": "text",
        "text": (
            "The user directly edited these workspace files. "
            "Treat the listed revisions as authoritative and read files "
            "before changing them: "
            + ", ".join(
                f"{edit.path} @ revision {edit.resulting_revision}"
                for edit in input.workspace_edits
            )
        ),
    }],
}
```

Do not include file content. Persist this message in the next normal model
checkpoint so crash recovery uses the same canonical transcript.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest -q \
  tests/coding/application/test_workspace_edit_safe_point.py \
  tests/coding/loop/test_anthropic_loop.py \
  tests/coding/integration/test_postgres_durability.py
.venv/bin/ruff check neos/coding tests/coding
git diff --check
git add neos/coding/loop/base.py neos/coding/application/run_service.py \
  neos/coding/repositories/run_repository.py neos/coding/loop/anthropic.py \
  tests/coding/fakes.py \
  tests/coding/application/test_workspace_edit_safe_point.py \
  tests/coding/loop/test_anthropic_loop.py \
  tests/coding/integration/test_postgres_durability.py
git commit -m "feat(coding): apply user edits at safe points"
```

### Task 4: Owner-Scoped Workspace REST and Snapshot Projection

**Files:**
- Modify: `neos/coding/application/workspace_service.py`
- Modify: `neos/coding/repositories/projection_repository.py`
- Modify: `neos/coding/application/snapshot_service.py`
- Modify: `neos/api/models/coding_models.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Modify: `neos/coding/runtime.py`
- Modify: `tests/coding/application/test_snapshot_service.py`
- Modify: `tests/api/handlers/test_coding_handlers.py`
- Create: `tests/coding/application/test_workspace_read_service.py`

**Interfaces:**
- Consumes: Task 2 service, Task 3 edit application state, sandbox
  `list_tree/read_file/git_diff`.
- Produces typed tree/file/diff/save endpoints and snapshot `user_edits`.

- [ ] **Step 1: Write failing read/API/snapshot tests**

```python
async def test_read_file_returns_revision_and_utf8_text() -> None:
    result = await service.read_file(
        task_id="ct_1", owner_id="u1", path="src/app.py"
    )
    assert result.content == "안녕\n"
    assert result.workspace_revision == "12"
    assert result.binary is False


def test_foreign_workspace_is_hidden() -> None:
    response = foreign.get(
        "/api/v1/coding/tasks/ct_1/workspace/tree"
    )
    assert response.status_code == 404
```

Cover bounded tree ordering, binary metadata without inline content, oversized
file/diff, invalid path, save `409`, duplicate save, and snapshot public fields.

- [ ] **Step 2: Run focused tests**

```bash
.venv/bin/pytest -q \
  tests/coding/application/test_workspace_read_service.py \
  tests/coding/application/test_snapshot_service.py \
  tests/api/handlers/test_coding_handlers.py
```

Expected: endpoint/model/service failures.

- [ ] **Step 3: Implement bounded service reads**

Define frozen results:

```python
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
```

Use existing path validation before opening the file. Decode UTF-8 strictly;
on `UnicodeDecodeError`, return `binary=True, content=None`. Reject a file over
the configured read limit before returning content. Truncate diff only at a
valid UTF-8 boundary and set `truncated=True`.

- [ ] **Step 4: Add typed REST models and handlers**

Add the exact endpoints from the design. Map stable conflicts:

```python
except WorkspaceEditConflict as error:
    code = str(error)
    status_code = 409 if code in {
        "workspace_revision_conflict",
        "workspace_edit_exists",
        "workspace_edit_reconcile_required",
    } else 422
    raise HTTPException(status_code=status_code, detail=code) from error
```

All handlers depend on `get_coding_workspace_service`; do not reach into the
sandbox provider directly.

- [ ] **Step 5: Project bounded `user_edits` in snapshot**

Query the latest 100 edits ordered by `created_at, edit_id`. API fields:

```python
class CodingWorkspaceEditSnapshot(BaseModel):
    edit_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: Literal["pending_agent_sync", "agent_synced", "reconcile_required"]
    applied_checkpoint_id: str | None
```

Exclude content, digest, bytes, actor, and raw error.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest -q \
  tests/coding/application/test_workspace_read_service.py \
  tests/coding/application/test_snapshot_service.py \
  tests/api/handlers/test_coding_handlers.py
.venv/bin/ruff check neos/coding neos/api/models/coding_models.py \
  neos/api/handlers/coding_handlers.py tests/coding tests/api
git diff --check
git add neos/coding/application/workspace_service.py \
  neos/coding/repositories/projection_repository.py \
  neos/coding/application/snapshot_service.py \
  neos/api/models/coding_models.py neos/api/handlers/coding_handlers.py \
  neos/coding/runtime.py \
  tests/coding/application/test_snapshot_service.py \
  tests/api/handlers/test_coding_handlers.py \
  tests/coding/application/test_workspace_read_service.py
git commit -m "feat(coding): expose owner scoped workspace files"
```

### Task 5: Kind-Bound Watcher and Interactive PTY WebSockets

**Files:**
- Create: `neos/coding/transport/workspace_tickets.py`
- Create: `neos/coding/application/workspace_stream_service.py`
- Create: `neos/api/handlers/coding_workspace_ws_handlers.py`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/api/main.py`
- Create: `tests/coding/transport/test_workspace_tickets.py`
- Create: `tests/coding/application/test_workspace_stream_service.py`
- Create: `tests/api/handlers/test_coding_workspace_ws_handlers.py`

**Interfaces:**
- Consumes: Task 4 ownership/binding service and existing replayable watcher/PTY.
- Produces:
  - `WorkspaceStreamKind = watcher|pty`
  - kind-bound `WorkspaceTicketStore`
  - `neos.coding.workspace.v1` and `neos.coding.pty.v1` handlers.

- [ ] **Step 1: Write failing ticket and WebSocket tests**

```python
async def test_ticket_is_one_time_and_kind_bound() -> None:
    token = await tickets.issue(
        owner_id="u1", task_id="ct_1", kind=WorkspaceStreamKind.PTY
    )
    assert await tickets.consume(
        token, task_id="ct_1", kind=WorkspaceStreamKind.WATCHER
    ) is None
    assert await tickets.consume(
        token, task_id="ct_1", kind=WorkspaceStreamKind.PTY
    ) == "u1"
    assert await tickets.consume(
        token, task_id="ct_1", kind=WorkspaceStreamKind.PTY
    ) is None
```

WebSocket tests cover wrong subprotocol, foreign task, watcher replay, watcher
gap, PTY create/connect, input, resize, replay, disconnect survival, explicit
kill, heartbeat, and slow-consumer closure.

- [ ] **Step 2: Run focused tests**

```bash
.venv/bin/pytest -q \
  tests/coding/transport/test_workspace_tickets.py \
  tests/coding/application/test_workspace_stream_service.py \
  tests/api/handlers/test_coding_workspace_ws_handlers.py
```

Expected: missing transport/service/handler failures.

- [ ] **Step 3: Implement kind-bound ticket stores**

```python
class WorkspaceStreamKind(StrEnum):
    WATCHER = "watcher"
    PTY = "pty"


class WorkspaceTicketStore(Protocol):
    @property
    def expires_in(self) -> int: ...

    async def issue(
        self, *, owner_id: str, task_id: str, kind: WorkspaceStreamKind
    ) -> str: ...

    async def consume(
        self, token: str, *, task_id: str, kind: WorkspaceStreamKind
    ) -> str | None: ...
```

Store `{owner_id, task_id, kind}` atomically in memory/Redis. A wrong-kind
consume must not burn the token; a matching consume deletes it.

- [ ] **Step 4: Implement stream service**

The service validates ownership before returning a bound session. Track PTYs
by `(task_id, pty_id)` with owner, last activity, and session handle. Reject
creation above `sandbox.workspace.pty_max_sessions`. Update activity on input,
resize, output, and reconnect. A background reaper kills sessions past
`sandbox.workspace.pty_idle_ttl_seconds` and all task PTYs on terminal task
state.

- [ ] **Step 5: Implement watcher and PTY protocols**

Watcher server frame:

```python
{
    "v": 1,
    "type": "workspace.changed",
    "cursor": event.cursor,
    "workspace_revision": event.value.workspace_revision,
    "changes": [
        {"path": change.path, "kind": change.kind.value,
         "previous_path": change.previous_path}
        for change in event.value.changes
    ],
}
```

PTY output frame:

```python
{
    "v": 1,
    "type": "pty.output",
    "cursor": event.cursor,
    "data": base64.b64encode(event.value.data).decode("ascii"),
}
```

Accept client `ping`, `pty.input`, and `pty.resize`. On `ReplayGap`, send the
kind-specific resync frame and close 1012. Sanitize close reasons.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest -q \
  tests/coding/transport/test_workspace_tickets.py \
  tests/coding/application/test_workspace_stream_service.py \
  tests/api/handlers/test_coding_workspace_ws_handlers.py \
  tests/coding/sandbox/test_memory_watcher.py \
  tests/coding/sandbox/test_memory_pty.py
.venv/bin/ruff check neos/coding neos/api/handlers \
  tests/coding tests/api/handlers
git diff --check
git add neos/coding/transport/workspace_tickets.py \
  neos/coding/application/workspace_stream_service.py \
  neos/api/handlers/coding_workspace_ws_handlers.py \
  neos/coding/runtime.py neos/api/main.py \
  tests/coding/transport/test_workspace_tickets.py \
  tests/coding/application/test_workspace_stream_service.py \
  tests/api/handlers/test_coding_workspace_ws_handlers.py
git commit -m "feat(coding): stream workspace watcher and pty"
```

### Task 6: Browser Workspace Data, Draft, and Stream Stores

**Files:**
- Modify: `web/features/coding/api/coding-api.ts`
- Create: `web/features/coding/workspace/types.ts`
- Create: `web/features/coding/workspace/workspace-store.ts`
- Create: `web/features/coding/workspace/workspace-stream-client.ts`
- Create: `web/features/coding/workspace/use-coding-workspace.ts`
- Create: `web/app/(code)/api/coding/tasks/[taskId]/workspace/[...path]/route.ts`
- Create: `web/tests/source/coding-workspace-store.test.ts`
- Create: `web/tests/source/coding-workspace-stream-client.test.ts`

**Interfaces:**
- Consumes: Tasks 4–5 REST/WS contracts and coding snapshot `user_edits`.
- Produces separate revision-keyed workspace state and PTY state consumed by Task 7.

- [ ] **Step 1: Write failing store and client tests**

```typescript
test("watcher invalidates queries without touching agent cursor", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateTree(treeAtRevision("12"));
  store.beginEdit(fileAtRevision("12"));
  store.applyWatcher(changeAtRevision("13", "src/app.py"));

  assert.equal(store.getSnapshot().draft?.content, "local draft");
  assert.equal(store.getSnapshot().editState, "revision_conflict");
  assert.equal(store.getSnapshot().workspaceRevision, "13");
});

test("pty reconnect keeps an independent cursor", () => {
  const state = reducePtyFrame(emptyPtyState(), outputFrame(7, "hello"));
  assert.equal(state.afterCursor, 7);
  assert.equal(state.output, "hello");
});
```

Also test stale response suppression, duplicate watcher frames, save pending,
synced event application, cursor gap, output cap, and terminal failure
isolation.

- [ ] **Step 2: Run focused source tests**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test \
  tests/source/coding-workspace-store.test.ts \
  tests/source/coding-workspace-stream-client.test.ts
```

Expected: missing module failures.

- [ ] **Step 3: Add typed API and BFF proxy**

Define `WorkspaceTree`, `WorkspaceFile`, `WorkspaceDiff`,
`WorkspaceFileSaveRequest/Result`, `WorkspaceUserEditView`, and
`WorkspaceWsTicket`. The catch-all BFF accepts only the known workspace
subpaths and methods, forwards the authenticated backend token, and never logs
request bodies.

- [ ] **Step 4: Implement isolated workspace store**

State must include:

```typescript
export type CodingWorkspaceState = {
  workspaceRevision: string | null;
  tree: WorkspaceTree | null;
  selectedPath: string | null;
  file: WorkspaceFile | null;
  diff: WorkspaceDiff | null;
  draft: { path: string; baseRevision: string; content: string } | null;
  editState:
    | "read_only" | "editing" | "saving"
    | "saved_pending_agent" | "agent_synced"
    | "revision_conflict";
  pendingEditId: string | null;
  watcherCursor: number;
  issue: string | null;
};
```

Watcher invalidation updates revision and clears stale tree/file/diff cache
except an active draft. If the selected path changed while editing, set
`revision_conflict`.

- [ ] **Step 5: Implement PTY replay store/client**

Keep `ptyId`, `afterCursor`, connection state, rows/cols, and a bounded output
rope/chunk deque outside React component state. Decode base64 to UTF-8 with a
streaming `TextDecoder`; cap rendered output by configured character count.
Reconnect obtains a fresh kind-bound ticket and resends the last cursor.

- [ ] **Step 6: Verify and commit**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test \
  tests/source/coding-workspace-store.test.ts \
  tests/source/coding-workspace-stream-client.test.ts
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
git add web/features/coding/api/coding-api.ts \
  web/features/coding/workspace \
  'web/app/(code)/api/coding/tasks/[taskId]/workspace/[...path]/route.ts' \
  web/tests/source/coding-workspace-store.test.ts \
  web/tests/source/coding-workspace-stream-client.test.ts
git commit -m "feat(coding): add workspace browser stores"
```

### Task 7: Resizable Files, Diff, and Terminal Dock

**Files:**
- Create: `web/features/coding/components/workspace/coding-workspace-dock.tsx`
- Create: `web/features/coding/components/workspace/coding-file-tree.tsx`
- Create: `web/features/coding/components/workspace/coding-file-viewer.tsx`
- Create: `web/features/coding/components/workspace/coding-diff-viewer.tsx`
- Create: `web/features/coding/components/workspace/coding-terminal.tsx`
- Create: `web/features/coding/components/workspace/workspace-dock-layout.ts`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Create: `web/tests/source/coding-workspace-dock.test.ts`
- Create: `web/tests/source/coding-file-editor.test.ts`
- Create: `web/tests/source/coding-terminal-ui.test.ts`

**Interfaces:**
- Consumes: Task 6 workspace hook/store.
- Produces approved B-layout UI with explicit Edit mode and mobile sheet.

- [ ] **Step 1: Write failing source and reducer tests**

```typescript
test("dock preserves ledger and exposes accessible workspace tabs", () => {
  const source = readFileSync(
    "features/coding/components/workspace/coding-workspace-dock.tsx", "utf8"
  );
  assert.match(source, /role="tablist"/);
  assert.match(source, /Files/);
  assert.match(source, /Diff/);
  assert.match(source, /Terminal/);
  assert.match(source, /aria-orientation="vertical"/);
});

test("file viewer is read only until Edit is explicit", () => {
  const state = beginEdit(readOnlyFileState());
  assert.equal(state.editState, "editing");
  assert.equal(state.draft?.baseRevision, "12");
});
```

Test dock width clamp/persistence, keyboard shortcuts, draft cancel, conflict
draft preservation, reload latest, compare changes, save/pending/synced labels,
PTY connection states, and mobile sheet source contract.

- [ ] **Step 2: Run focused tests**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test \
  tests/source/coding-workspace-dock.test.ts \
  tests/source/coding-file-editor.test.ts \
  tests/source/coding-terminal-ui.test.ts
```

Expected: missing component failures.

- [ ] **Step 3: Implement dock layout and accessibility**

Use a CSS grid with a persisted width clamped by:

```typescript
export const clampDockWidth = (width: number, viewport: number) =>
  Math.min(Math.max(width, 320), Math.min(720, viewport * 0.55));
```

The separator is focusable, `role="separator"`,
`aria-orientation="vertical"`, and supports arrow keys. Use
`role="tablist"`, `role="tab"`, and `role="tabpanel"`. On the mobile
breakpoint render the same dock content in the existing sheet primitive and
preserve ledger scroll by not remounting its store.

- [ ] **Step 4: Implement file and diff views**

The viewer renders plain text without raw HTML. `Edit` creates a local draft;
`Save` sends a generated `edit_id` and the immutable base revision. On conflict
keep the draft and offer:

- `Reload latest`: explicit confirmation, then replace draft.
- `Compare changes`: switch to Diff with draft/latest comparison.

Status copy is exactly:

- `Saved · agent sync pending`
- `Agent synced at checkpoint {id}`
- `File changed since editing began`

- [ ] **Step 5: Implement terminal view**

Render a bounded `<pre>` output surface and a text input without
`dangerouslySetInnerHTML`. Show create/connect/reconnecting/closed/failed
states. ResizeObserver emits bounded rows/cols. Terminal errors remain inside
the Terminal tab and never change the coding connection banner.

- [ ] **Step 6: Integrate workspace task layout**

Replace the fixed detail aside with:

```tsx
<CodingWorkspaceDock
  taskId={taskId}
  projection={projection}
  codingConnection={connection}
/>
```

Keep execution ledger, output ledger, phases, approvals, and steering order
unchanged. Shortcuts:

- `Cmd/Ctrl+Shift+E`: Files
- `Cmd/Ctrl+Shift+D`: Diff
- ``Cmd/Ctrl+Shift+` ``: Terminal

- [ ] **Step 7: Verify and commit**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test \
  tests/source/coding-workspace-dock.test.ts \
  tests/source/coding-file-editor.test.ts \
  tests/source/coding-terminal-ui.test.ts
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
git add web/features/coding/components/workspace \
  web/features/coding/components/coding-task-workspace.tsx \
  web/tests/source/coding-workspace-dock.test.ts \
  web/tests/source/coding-file-editor.test.ts \
  web/tests/source/coding-terminal-ui.test.ts
git commit -m "feat(coding): add resizable workspace dock"
```

### Task 8: Docker Vertical Slice, Operations, and Full Verification

**Files:**
- Create: `tests/coding/test_workspace_gateway_vertical_slice.py`
- Create: `tests/coding/integration/test_docker_workspace_gateway.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: Tasks 1–7 complete feature.
- Produces deterministic memory coverage, opt-in Docker proof, rollout/rollback documentation, and final verification evidence.

- [ ] **Step 1: Write end-to-end memory vertical test**

```python
async def test_user_edit_reaches_agent_once_and_survives_reconnect(harness) -> None:
    saved = await harness.workspace.save_file(
        task_id=harness.task_id, owner_id="u1", edit_id="cwe_1",
        path="src/app.py", base_revision="1", content="def add(a, b): return a + b\n",
    )
    watcher = await harness.reconnect_watcher(after_cursor=0)
    await harness.advance_until_complete(worker_id="worker-1")
    snapshot = await harness.snapshots.get_owned(harness.task_id, "u1")

    assert saved.resulting_revision == "2"
    assert watcher[-1]["workspace_revision"] == 2
    assert snapshot.workspace.user_edits[0].status == "agent_synced"
    assert harness.model.workspace_edit_context_count("cwe_1") == 1
```

Also assert file content and PTY bytes never occur in public coding events.

- [ ] **Step 2: Add guarded Docker vertical test**

Guard with the existing Docker availability marker. The test creates a real
Docker sandbox, reads the tree, saves with revision, receives watcher change,
opens PTY, runs the fixture test, reconnects PTY from its cursor, and confirms
cleanup. It must keep digest-pinned image, non-root user, read-only root,
capability drop, limits, and `network=none`.

- [ ] **Step 3: Document operations**

Add to `docs/NEOS_CODING.md`:

- migration 044 and edit state machine
- REST/WS contracts and independent cursors
- safe-point exactly-once semantics
- reconciliation and alert threshold
- PTY idle/session limits
- privacy/audit boundary
- backend capability-gated Edit rollout
- disable Edit/PTY create first during rollback
- retain rows/events; never auto-mark pending edits applied

- [ ] **Step 4: Run complete backend verification**

```bash
.venv/bin/pytest -q tests/coding \
  tests/api/handlers/test_coding_handlers.py \
  tests/api/handlers/test_coding_workspace_ws_handlers.py \
  tests/config/test_sandbox_config.py
.venv/bin/ruff check neos/coding \
  neos/api/handlers/coding_handlers.py \
  neos/api/handlers/coding_workspace_ws_handlers.py \
  neos/api/models/coding_models.py \
  tests/coding tests/api/handlers
```

Expected: all non-opt-in tests pass; Docker/PostgreSQL tests skip only for
their existing explicit environment guards.

- [ ] **Step 5: Run complete frontend verification**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm run test:source
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
git status --short
```

Expected: all source tests and TypeScript pass; status shows only intended
Task 8 files plus the preserved unrelated user files.

- [ ] **Step 6: Commit final vertical slice**

```bash
git add tests/coding/test_workspace_gateway_vertical_slice.py \
  tests/coding/integration/test_docker_workspace_gateway.py \
  docs/NEOS_CODING.md
git commit -m "test(coding): verify workspace gateway recovery"
```

Do not modify or stage the user-owned `.env.template`.

## Final Review Checklist

- [ ] Foreign tasks are hidden consistently across REST and both WebSockets.
- [ ] Conditional save rejects stale revision without mutating the workspace.
- [ ] Duplicate `edit_id` never writes the file twice.
- [ ] Ambiguous sandbox writes remain reconcile-required until exact digest/revision proof.
- [ ] Public event/snapshot data contains no file body, digest, terminal bytes, command, or actor.
- [ ] Safe-point checkpoint and edit sync state commit atomically under fencing.
- [ ] Replacement workers cannot inject or sync an edit twice.
- [ ] Watcher, PTY, and coding cursors are independent.
- [ ] PTY survives disconnect but obeys explicit kill, idle TTL, task terminal, and suspend cleanup.
- [ ] Edit conflict preserves the browser draft and never auto-merges.
- [ ] Execution ledger order and 10k event frame batching remain unchanged.
- [ ] Desktop dock, mobile sheet, tabs, splitter, keyboard access, and live status are verified.
- [ ] Memory vertical slice passes and Docker/PostgreSQL integrations use explicit opt-in guards.
