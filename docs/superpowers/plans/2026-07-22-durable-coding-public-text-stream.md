# Durable Coding Public Text Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and stream bounded assistant-visible coding text as ordered parts that converge across snapshot, replay, and live delivery.

**Architecture:** Fenced run-repository commands atomically update a `coding_text_parts` materialized projection and append matching events/outbox rows. The real model loop uses those commands for part lifecycle, the repeatable-read snapshot exposes typed parts, and the browser reduces snapshot/live events into the existing frame-batched projection store.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLAlchemy/PostgreSQL, pytest, TypeScript/React, Node test runner via `tsx`.

## Global Constraints

- Persist only provider-normalized assistant `TextDelta.text` as public content.
- Never persist reasoning, `ToolInputDelta.partial_json`, prompts, tool input, env, stdin, stdout, stderr, or file contents in text-part events.
- `max_text_delta_bytes=16384` and `max_public_text_bytes=1048576` by default.
- Enforce `max_text_delta_bytes <= max_public_text_bytes <= max_transcript_bytes`.
- All text-part writes validate the current execution lease and canonical running run.
- Snapshot replacement clears projection issues; unknown live part references trigger durable resync.
- Do not add runtime dependencies.
- Preserve unrelated `.env.template`, `docs/TODO_260729.md`, and untracked deep-analysis documents.

---

### Task 1: Text-Part Domain, Limits, and Migration 043

**Files:**
- Create: `neos/coding/domain/text_parts.py`
- Create: `db/migrations/043_add_coding_text_parts.sql`
- Modify: `neos/config/schema.py`
- Modify: `neos/coding/loop/anthropic.py`
- Create: `tests/coding/domain/test_text_parts.py`
- Create: `tests/coding/test_migration_043_contract.py`
- Modify: `tests/config/test_coding_model_config.py`

**Interfaces:**
- Produces: `CodingTextPart`, `TextPartStatus`, `ModelTextPartCommit`, `TextPartConflict`, and validated text byte limits.

- [ ] **Step 1: Write failing domain/config/migration tests**

Add tests that construct streaming/completed/interrupted parts, reject negative bytes and invalid status transitions, assert config defaults and ordering validation, and inspect migration SQL for owner-linked foreign keys, status check, unique task/turn, and task ordering index.

```python
def test_text_limits_are_ordered() -> None:
    with pytest.raises(ValidationError):
        CodingModelConfig(
            max_text_delta_bytes=20,
            max_public_text_bytes=10,
            max_transcript_bytes=100,
        )


def test_migration_has_bounded_part_contract() -> None:
    sql = Path("db/migrations/043_add_coding_text_parts.sql").read_text()
    assert "CHECK (status IN ('streaming', 'completed', 'interrupted'))" in sql
    assert "UNIQUE (task_id, turn_id)" in sql
    assert "idx_coding_text_parts_task_first_seq" in sql
```

- [ ] **Step 2: Run tests and verify missing contracts**

Run:

```bash
.venv/bin/pytest tests/coding/domain/test_text_parts.py \
  tests/coding/test_migration_043_contract.py \
  tests/config/test_coding_model_config.py -q
```

Expected: collection or assertions fail because the domain module, migration, and config fields do not exist.

- [ ] **Step 3: Implement domain types**

Create `text_parts.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.domain.events import CodingEvent


class TextPartStatus(StrEnum):
    STREAMING = "streaming"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class CodingTextPart:
    part_id: str
    task_id: str
    run_id: str
    turn_id: str
    first_seq: int
    last_seq: int
    status: TextPartStatus
    content: str
    content_bytes: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not all((self.part_id, self.task_id, self.run_id, self.turn_id)):
            raise ValueError("text part identities are required")
        if self.first_seq < 1 or self.last_seq < self.first_seq:
            raise ValueError("text part sequence range is invalid")
        if self.content_bytes != len(self.content.encode("utf-8")):
            raise ValueError("text part byte count must match content")


@dataclass(frozen=True, slots=True)
class ModelTextPartCommit:
    part: CodingTextPart
    event: CodingEvent
    interrupted_part_ids: tuple[str, ...] = ()


class TextPartConflict(RuntimeError):
    pass
```

- [ ] **Step 4: Add strict config and runtime-loop fields**

Add to `CodingModelConfig` and `AnthropicLoopConfig`:

```python
max_text_delta_bytes: int = Field(default=16_384, gt=0)
max_public_text_bytes: int = Field(default=1_048_576, gt=0)
```

For the dataclass use integer defaults and include them in positive validation. Extend the Pydantic model validator:

```python
if not (
    self.max_text_delta_bytes
    <= self.max_public_text_bytes
    <= self.max_transcript_bytes
):
    raise ValueError("coding public text byte limits are invalid")
```

Wire both fields in `_prepare_real_coding_loop()`.

- [ ] **Step 5: Add migration 043**

Create the table and indexes exactly as specified in the design, using `ON DELETE CASCADE`, `BIGINT` sequence/byte columns, and:

```sql
CREATE INDEX IF NOT EXISTS idx_coding_text_parts_task_first_seq
    ON coding_text_parts(task_id, first_seq, part_id);
CREATE INDEX IF NOT EXISTS idx_coding_text_parts_task_status
    ON coding_text_parts(task_id, status);
```

- [ ] **Step 6: Verify and commit**

Run the Step 2 command plus Ruff on changed Python files. Then:

```bash
git add neos/coding/domain/text_parts.py db/migrations/043_add_coding_text_parts.sql \
  neos/config/schema.py neos/coding/loop/anthropic.py neos/coding/runtime.py \
  tests/coding/domain/test_text_parts.py tests/coding/test_migration_043_contract.py \
  tests/config/test_coding_model_config.py
git commit -m "feat(coding): define durable public text parts"
```

### Task 2: Atomic Fenced Text-Part Repository Commands

**Files:**
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/repositories/test_text_part_repository.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`

**Interfaces:**
- Consumes: Task 1 domain types and existing event/outbox/lease helpers.
- Produces: `start_model_text_part`, `append_model_text_delta`, and `complete_model_text_part` on `CodingRunRepository`.

- [ ] **Step 1: Write failing repository tests**

Cover start, Unicode append, completion, replacement interruption, cumulative limit rollback, wrong turn/part, completed append, stale lease, and duplicate start. Assert sequence monotonicity and sanitized payloads.

```python
commit = await repository.append_model_text_delta(
    lease=lease,
    part_id="ctp_1",
    turn_id="turn_1",
    delta="안녕",
    delta_bytes=6,
    max_part_bytes=10,
    now=NOW,
)
assert commit.part.content == "안녕"
assert commit.part.content_bytes == 6
assert commit.event.payload == {"part_id": "ctp_1", "delta": "안녕"}
```

- [ ] **Step 2: Run tests and verify protocol methods are missing**

```bash
.venv/bin/pytest tests/coding/repositories/test_text_part_repository.py \
  tests/coding/integration/test_postgres_durability.py -q
```

Expected: failures for missing repository commands.

- [ ] **Step 3: Extend the repository protocol**

Add the three signatures from the design to `CodingRunRepository`, returning `ModelTextPartCommit`.

- [ ] **Step 4: Implement PostgreSQL start**

Within one `session.begin()`:

1. call `_validate_lease_in_session`;
2. lock the canonical running run;
3. allocate one sequence;
4. update same-task/run streaming rows to interrupted with that `last_seq`;
5. insert the new part;
6. insert `model.text_part.started` using `_insert_event_in_session`.

Pass `interrupted_part_ids` as a JSON list and call `_wake_outbox` only after transaction exit.
If the unique task/turn or part identity already exists, raise `TextPartConflict("model_text_part_exists")`; do not allocate a lasting sequence, event, or outbox row because the transaction rolls back.

- [ ] **Step 5: Implement PostgreSQL delta and completion**

Delta SQL must enforce the byte cap in the update predicate:

```sql
UPDATE coding_text_parts
SET content = content || :delta,
    content_bytes = content_bytes + :delta_bytes,
    last_seq = :seq,
    updated_at = :now
WHERE part_id = :part_id AND task_id = :task_id AND run_id = :run_id
  AND turn_id = :turn_id AND status = 'streaming'
  AND content_bytes + :delta_bytes <= :max_part_bytes
RETURNING part_id, task_id, run_id, turn_id, first_seq, last_seq,
          status, content, content_bytes, created_at, updated_at
```

If no row returns, distinguish missing/non-streaming identity from byte-budget conflict with a locked metadata query and raise `TextPartConflict("model_public_text_budget_exceeded")` or `TextPartConflict("model_text_part_stale")`. The transaction rolls back its allocated sequence and event.

Completion performs a status-only streaming-to-completed update and appends `model.text_part.completed` atomically.

- [ ] **Step 6: Implement in-memory parity**

Add `text_parts`, an async-lock-protected key map, identical identity/status/byte checks, event sequence updates, and interruption behavior to `InMemoryCodingRunRepository`.

- [ ] **Step 7: Verify and commit**

Run Step 2 and repository/application coding tests, then:

```bash
git add neos/coding/loop/base.py neos/coding/repositories/run_repository.py \
  tests/coding/fakes.py tests/coding/repositories/test_text_part_repository.py \
  tests/coding/integration/test_postgres_durability.py
git commit -m "feat(coding): persist model text parts under fencing"
```

### Task 3: Real Model Loop Text Lifecycle and Crash Recovery

**Files:**
- Modify: `neos/coding/loop/anthropic.py`
- Modify: `tests/coding/loop/test_anthropic_loop.py`
- Modify: `tests/coding/test_real_model_tool_loop_crash_recovery.py`
- Modify: `tests/coding/conftest.py`

**Interfaces:**
- Consumes: Task 2 repository commands.
- Produces: fenced `model.text_part.started`, `model.text_delta`, and `model.text_part.completed` events.

- [ ] **Step 1: Write failing loop tests**

Assert one start, ordered deltas with one part ID, one completion, tool-input content absence, Unicode byte enforcement, cumulative failure, and crash/replacement interruption.

```python
events = await collect(harness_with_text("hel", "lo"))
assert [event.type for event in events[:4]] == [
    "model.text_part.started",
    "model.text_delta",
    "model.text_delta",
    "model.text_part.completed",
]
assert events[1].payload["delta"] == "hel"
assert len({event.payload["part_id"] for event in events[:4]}) == 1
```

- [ ] **Step 2: Run loop/crash tests and verify byte-only behavior**

```bash
.venv/bin/pytest tests/coding/loop/test_anthropic_loop.py \
  tests/coding/test_real_model_tool_loop_crash_recovery.py -q
```

Expected: new tests fail because current text events contain only byte counts.

- [ ] **Step 3: Implement lifecycle**

Generate `part_id=f"ctp_{uuid4().hex}"` beside `turn_id`, start it before `model.stream`, and yield the start event. For each `TextDelta`:

```python
delta_bytes = len(model_event.text.encode("utf-8"))
if delta_bytes > self._config.max_text_delta_bytes:
    raise CodingLoopFailure("model_text_delta_too_large", retryable=False)
try:
    commit = await deps.repository.append_model_text_delta(
        lease=lease,
        part_id=part_id,
        turn_id=request.turn_id,
        delta=model_event.text,
        delta_bytes=delta_bytes,
        max_part_bytes=self._config.max_public_text_bytes,
        now=self._clock(),
    )
except TextPartConflict as error:
    raise CodingLoopFailure(str(error), retryable=False) from error
yield commit.event
```

After `ModelCompleted`, complete and yield the part before existing checkpoint/tool handling. Keep `model.tool_input_delta` content-free.

- [ ] **Step 4: Verify crash semantics**

Inject a crash after one persisted delta. After lease expiry and replacement advance, assert the first part is interrupted, a new ordered part is created, the stale lease cannot append, and no delta is duplicated within either part.

- [ ] **Step 5: Verify and commit**

Run Step 2 plus all loop/worker tests, Ruff, and diff check. Commit:

```bash
git add neos/coding/loop/anthropic.py tests/coding/loop/test_anthropic_loop.py \
  tests/coding/test_real_model_tool_loop_crash_recovery.py tests/coding/conftest.py
git commit -m "feat(coding): stream fenced public model text"
```

### Task 4: Owner-Scoped Snapshot and Typed API Parts

**Files:**
- Modify: `neos/coding/repositories/projection_repository.py`
- Modify: `neos/coding/application/snapshot_service.py`
- Modify: `neos/api/models/coding_models.py`
- Modify: `tests/coding/application/test_snapshot_service.py`
- Modify: `tests/api/handlers/test_coding_handlers.py`

**Interfaces:**
- Consumes: `coding_text_parts` rows.
- Produces: `parts: tuple[CodingTextPartProjection, ...]` and typed `CodingTextPartSnapshot` API output.

- [ ] **Step 1: Write failing snapshot/API tests**

Fixture two ordered parts with Unicode content and assert owner scoping, status typing, ordering, and absence of `content_bytes`, prompt, actor, and checkpoint loop state from each serialized part.

- [ ] **Step 2: Run focused tests**

```bash
.venv/bin/pytest tests/coding/application/test_snapshot_service.py \
  tests/api/handlers/test_coding_handlers.py -q
```

Expected: failures because snapshot responses have no `parts` field.

- [ ] **Step 3: Add repository and service projections**

Create `CodingTextPartRow` and query:

```sql
SELECT part_id, run_id, turn_id, status, content, first_seq, last_seq
FROM coding_text_parts
WHERE task_id = :task_id
ORDER BY first_seq ASC, part_id ASC
```

Run it inside the existing repeatable-read transaction. Map to a frozen `CodingTextPartProjection` with `TextPartStatus`.

- [ ] **Step 4: Add typed API model**

```python
class CodingTextPartSnapshot(BaseModel):
    part_id: str
    run_id: str
    turn_id: str
    status: Literal["streaming", "completed", "interrupted"]
    content: str
    first_seq: int
    last_seq: int
```

Add `parts: list[CodingTextPartSnapshot]` to `CodingProjectionSnapshotResponse`.

- [ ] **Step 5: Verify and commit**

Run focused tests, all API handler tests, Ruff, then:

```bash
git add neos/coding/repositories/projection_repository.py \
  neos/coding/application/snapshot_service.py neos/api/models/coding_models.py \
  tests/coding/application/test_snapshot_service.py \
  tests/api/handlers/test_coding_handlers.py
git commit -m "feat(coding): expose durable public text snapshot"
```

### Task 5: Browser Part Projection, Resync, and Frame Batching

**Files:**
- Modify: `web/features/coding/types/projection.ts`
- Modify: `web/features/coding/stream/projection-reducer.ts`
- Modify: `web/features/coding/stream/coding-projection-store.ts`
- Modify: `web/features/coding/stream/use-coding-stream.ts`
- Create: `web/tests/source/coding-text-part-projection.test.ts`
- Modify: `web/tests/source/coding-projection-frame-batching.test.ts`
- Modify: `web/tests/source/coding-stream-client.test.ts`

**Interfaces:**
- Consumes: typed snapshot and three text lifecycle events.
- Produces: ordered `textPartsById`, `orderedTextPartIds`, and `ProjectionApplyOutcome`.

- [ ] **Step 1: Write failing reducer/store/hook tests**

Cover snapshot/full replay/tail convergence, Unicode concatenation, interruption, duplicate suppression, unknown part resync, and 10,000 delta frame batching.

- [ ] **Step 2: Run focused source tests**

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test tests/source/coding-text-part-projection.test.ts \
  tests/source/coding-projection-frame-batching.test.ts \
  tests/source/coding-stream-client.test.ts
```

Expected: failures for missing part types and reducer cases.

- [ ] **Step 3: Add projection types and hydration**

Implement `CodingTextPartView`, `textPartsById`, `orderedTextPartIds`, and `projectionIssue`. Snapshot hydration sorts parts by `first_seq` then `part_id`.

- [ ] **Step 4: Add lifecycle reducer cases**

Started events interrupt listed IDs and insert once. Delta/completion events require an existing part. On unknown reference, leave `appliedSeq` unchanged and set:

```ts
projectionIssue: { code: "unknown_text_part", eventSeq: event.seq }
```

Snapshot replacement clears the issue.

- [ ] **Step 5: Return store apply outcomes and reconnect**

```ts
export type ProjectionApplyOutcome =
  | "applied"
  | "duplicate"
  | "resync_required";
```

`applyEvent` returns duplicate for the same state, immediately publishes and returns resync for a projection issue, otherwise schedules/publishes as before. In `useCodingStream`, if the outcome is `resync_required`, set the existing resync flag, close the socket with code 1012, hydrate snapshot, then reconnect. Do not advance the durable cursor for the rejected event.

- [ ] **Step 6: Verify and commit**

Run focused tests, `pnpm test:source`, and `pnpm exec tsc --noEmit`; restore `tsconfig.tsbuildinfo`. Commit:

```bash
git add web/features/coding/types/projection.ts \
  web/features/coding/stream/projection-reducer.ts \
  web/features/coding/stream/coding-projection-store.ts \
  web/features/coding/stream/use-coding-stream.ts \
  web/tests/source/coding-text-part-projection.test.ts \
  web/tests/source/coding-projection-frame-batching.test.ts \
  web/tests/source/coding-stream-client.test.ts
git commit -m "feat(coding): project durable model text in browser"
```

### Task 6: Plain-Text Output Ledger, Vertical Slice, and Operations

**Files:**
- Create: `web/features/coding/components/coding-output-ledger.tsx`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Create: `web/tests/source/coding-output-ledger.test.ts`
- Create: `tests/coding/test_public_text_stream_vertical_slice.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: ordered text-part projection.
- Produces: accessible plain-text output UI and full reconnect/security verification.

- [ ] **Step 1: Write failing UI and vertical-slice tests**

UI source tests assert ledger placement above phases, `whitespace-pre-wrap`, status text, `aria-live="polite"` only for streaming, and absence of markdown/raw HTML rendering. Backend vertical slice runs partial text, replacement, completion, snapshot, and replay assertions while verifying tool partial JSON never appears.

- [ ] **Step 2: Implement the ledger**

Render non-empty ordered parts using `<pre>` or a `whitespace-pre-wrap` text container. Label streaming as “Writing”, completed as “Completed”, interrupted as “Interrupted”. Pass text as a React child; never use `dangerouslySetInnerHTML`.

- [ ] **Step 3: Integrate workspace placement**

Render `CodingOutputLedger` after the execution-ledger heading and before `PhaseTimeline`, without changing approval/composer order.

- [ ] **Step 4: Document operations**

Add migration/config/event contracts, byte failure codes, fenced write behavior, incomplete-part recovery, privacy boundary, rollout order, retention, and rollback rules to `docs/NEOS_CODING.md`.

- [ ] **Step 5: Run complete verification**

```bash
.venv/bin/pytest tests/coding tests/api/handlers/test_coding_handlers.py \
  tests/config/test_coding_model_config.py -q
.venv/bin/ruff check neos/coding neos/api/handlers/coding_handlers.py \
  neos/api/models/coding_models.py tests/coding tests/api/handlers/test_coding_handlers.py
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm run test:source
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
```

Restore `web/tsconfig.tsbuildinfo`, then run `git diff --check` and inspect status for unrelated user files.

- [ ] **Step 6: Commit vertical slice**

```bash
git add web/features/coding/components/coding-output-ledger.tsx \
  web/features/coding/components/coding-task-workspace.tsx \
  web/tests/source/coding-output-ledger.test.ts \
  tests/coding/test_public_text_stream_vertical_slice.py docs/NEOS_CODING.md
git commit -m "test(coding): verify durable public text recovery"
```

## Final Review Checklist

- [ ] Every public delta is fenced and atomically paired with event/outbox/projection state.
- [ ] Snapshot parts and event tail share one repeatable-read head.
- [ ] stale workers cannot append or complete text.
- [ ] delta and cumulative limits use UTF-8 bytes and reject before persistence.
- [ ] reasoning and tool partial JSON remain content-free.
- [ ] replacement attempts interrupt only streaming parts in the canonical run.
- [ ] snapshot/full replay/snapshot+tail produce identical ordered parts.
- [ ] unknown references resync without cursor advancement.
- [ ] 10,000 deltas retain one frame publish behavior.
- [ ] UI renders text as plain content with accessible lifecycle labels.
- [ ] backend/frontend/static verification passes with no unrelated changes committed.
