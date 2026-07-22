# Durable Coding Public Text Stream Design

**Date:** 2026-07-22

**Status:** Approved for written specification review

## 1. Goal

Stream assistant-visible coding output into the Code workspace and restore the same ordered text parts after reconnect. Snapshot, replay, and live delivery must converge without exposing private reasoning, tool input fragments, prompts, environment values, or sandbox content.

This slice follows the frame-batched projection work. It renders bounded plain text only. Markdown block memoization, reasoning summaries, rich tool renderers, and virtualization remain later Phase 4 slices.

## 2. Current Contract Gap

The real loop emits `model.text_delta` events containing only `{bytes}`. The frontend's isolated legacy reducer expects a different, unused `text.delta` payload containing `part_id` and `delta`. Production projection state has no ordered assistant parts.

Adding `delta` to events alone is insufficient. A reconnect snapshot advances the client to `head_seq`, so events at or before that head are not replayed. The accumulated text therefore needs a materialized server projection included in the same repeatable-read snapshot.

## 3. Security Boundary

Only `TextDelta.text`, which is the provider-normalized assistant output intended for the user, may enter the public text contract.

The following remain content-free:

- provider reasoning or chain-of-thought;
- `ToolInputDelta.partial_json`;
- normalized or raw tool inputs;
- user prompt and system instructions in text-part events;
- command argv, stdin, environment values, stdout, and stderr;
- file contents and secrets.

`model.tool_input_delta` continues to expose only `tool_call_id` and UTF-8 byte count. Audit and metric labels never contain text content, part IDs, task IDs, or turn IDs.

## 4. Limits and Failure Policy

Extend `CodingModelConfig` and `AnthropicLoopConfig` with:

```yaml
coding_model:
  max_text_delta_bytes: 16384
  max_public_text_bytes: 1048576
```

Both values are positive. `max_text_delta_bytes <= max_public_text_bytes <= max_transcript_bytes` is required at startup.

Before persistence, every delta is measured as UTF-8 bytes. A delta above the per-delta limit fails the run with stable non-retryable code `model_text_delta_too_large`. A part whose next append would exceed the cumulative limit fails with `model_public_text_budget_exceeded`. The rejected bytes are never stored or published. Existing durable partial text remains visible with `interrupted` status after replacement-worker reconciliation.

The system does not silently truncate assistant text because truncation could change code, commands, or safety explanations while appearing complete.

## 5. Durable Data Model

Migration `043_add_coding_text_parts.sql` creates:

```sql
CREATE TABLE coding_text_parts (
    part_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    first_seq BIGINT NOT NULL,
    last_seq BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('streaming', 'completed', 'interrupted')),
    content TEXT NOT NULL DEFAULT '',
    content_bytes BIGINT NOT NULL DEFAULT 0 CHECK (content_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, turn_id)
);
```

Indexes cover `(task_id, first_seq)` and `(task_id, status)`. `part_id` uses `ctp_<uuid hex>`. Ordering is always `first_seq, part_id`; clients never infer ordering from IDs.

## 6. Fenced Repository Commands

Model stream mutations move from the unfenced general event service to explicit `CodingRunRepository` commands. Every command locks and validates the current execution lease before changing the part projection or appending its event/outbox.

```python
async def start_model_text_part(
    *, lease: ExecutionLease, part_id: str, turn_id: str, now: datetime
) -> ModelTextPartCommit: ...

async def append_model_text_delta(
    *, lease: ExecutionLease, part_id: str, turn_id: str,
    delta: str, delta_bytes: int, max_part_bytes: int, now: datetime
) -> ModelTextPartCommit: ...

async def complete_model_text_part(
    *, lease: ExecutionLease, part_id: str, turn_id: str, now: datetime
) -> ModelTextPartCommit: ...
```

`ModelTextPartCommit` returns the current materialized part and the durable event.

### 6.1 Start

`start_model_text_part` performs one transaction:

1. validate the canonical run and current fencing token;
2. mark any `streaming` part for the same task/run as `interrupted`, with its `last_seq` and `updated_at` set to the new start event boundary;
3. allocate the next task sequence;
4. insert the new empty `streaming` part with `first_seq = last_seq = seq`;
5. append `model.text_part.started` and its outbox row.

The event payload is:

```json
{
  "part_id": "ctp_...",
  "status": "streaming",
  "interrupted_part_ids": ["ctp_previous"]
}
```

This makes replacement-worker recovery explicit for both snapshot and live clients.

### 6.2 Delta

`append_model_text_delta` validates part identity, streaming status, and lease. The SQL update requires `content_bytes + :delta_bytes <= :max_part_bytes`, appends text, updates byte count and `last_seq`, then appends `model.text_delta` plus outbox in the same transaction.

```json
{"part_id":"ctp_...","delta":"public assistant text"}
```

A missing/stale/non-streaming part fails closed. A byte-budget conflict maps to `model_public_text_budget_exceeded` without persisting the rejected event.

### 6.3 Completion

After the provider emits `ModelCompleted`, the loop calls `complete_model_text_part` before checkpoint/tool advancement. The transaction validates the lease and part, marks it `completed`, allocates a sequence, and appends `model.text_part.completed` plus outbox.

```json
{"part_id":"ctp_...","status":"completed"}
```

If the worker crashes after part completion but before the model checkpoint, the completed public output remains durable. A replacement model attempt creates a new part rather than mutating completed history.

## 7. Loop Data Flow

For each model turn:

```text
create turn_id + part_id
  -> fenced start_model_text_part
  -> provider stream
       TextDelta
         -> validate per-delta and cumulative byte limits
         -> fenced append_model_text_delta
         -> yield durable event
       ToolInputDelta
         -> existing content-free byte event
       ToolCallCompleted / ModelCompleted
         -> retain canonical model semantics
  -> fenced complete_model_text_part
  -> existing model checkpoint or tool path
```

An empty assistant turn still creates and completes an empty part. The frontend may omit empty completed parts from rendering, but the lifecycle remains deterministic.

## 8. Snapshot Projection and API

`PostgresCodingProjectionRepository` reads `coding_text_parts` inside the existing repeatable-read owner-scoped snapshot transaction. It selects only:

- `part_id`, `run_id`, `turn_id`;
- `status`;
- `content`;
- `first_seq`, `last_seq`.

The public API adds typed `parts: list[CodingTextPartSnapshot]`. It does not expose byte counters, actor data, prompts, checkpoint loop state, or provider metadata through the part object.

The in-memory projection fixture receives equivalent rows for deterministic tests.

## 9. Browser Projection

Add:

```ts
export type CodingTextPartView = {
  part_id: string;
  run_id: string;
  turn_id: string;
  status: "streaming" | "completed" | "interrupted";
  content: string;
  first_seq: number;
  last_seq: number;
};
```

`CodingProjectionState` stores:

```ts
textPartsById: Record<string, CodingTextPartView>;
orderedTextPartIds: string[];
projectionIssue: { code: "unknown_text_part"; eventSeq: number } | null;
```

Snapshot hydration sorts by `first_seq, part_id`. Live events follow these rules:

- `model.text_part.started`: mark listed prior parts interrupted, add the new part once;
- `model.text_delta`: append only to the matching streaming part and update `last_seq`;
- `model.text_part.completed`: mark the matching part completed;
- duplicate `seq` events remain ignored by the existing projection reducer;
- unknown part references do not advance `appliedSeq`; they set `projectionIssue` and trigger snapshot resync rather than fabricating state.

The store changes `applyEvent(event)` to return `"applied" | "duplicate" | "resync_required"`. A text delta/completion with no known part publishes the issue immediately and returns `resync_required`. `useCodingStream()` closes the current socket with the existing resync close code and hydrates a new snapshot. Snapshot replacement clears `projectionIssue`. Existing callers may ignore the return value.

The existing frame-batched store coalesces delta-heavy updates to one subscriber notification per frame.

## 10. Initial UI

Add an assistant output ledger above the phase timeline. It renders ordered non-empty parts as plain text using `white-space: pre-wrap` and preserves the existing terminal-ledger visual language.

- `streaming`: visible text label and `aria-live="polite"` only on the active block;
- `completed`: stable block with no live region;
- `interrupted`: explicit interrupted label; partial content remains visible;
- no markdown parsing, syntax highlighting, raw HTML, or link activation in this slice.

The active prompt composer and approval cards remain in their existing order.

## 11. Tests

Backend tests cover:

1. start/delta/complete update part, event, task sequence, and outbox atomically;
2. stale fencing tokens cannot append text;
3. replacement start interrupts only streaming parts in the same task/run;
4. per-delta and cumulative UTF-8 limits reject before persistence;
5. tool input partial JSON remains absent from public events;
6. snapshot returns owner-scoped typed parts without private fields;
7. crash after partial output followed by replacement produces interrupted + new ordered parts.

Frontend tests cover:

1. snapshot, full replay, and snapshot plus live tail converge;
2. Unicode deltas concatenate without reordering;
3. unknown-part delta causes protocol resync state;
4. 10,000 deltas still schedule and notify once per frame;
5. plain-text UI renders completed, streaming, and interrupted states accessibly;
6. reconnect never duplicates a part or delta.

## 12. Rollout and Rollback

Rollout order is migration 043, backend repository/loop/API, then browser projection/UI. A browser deployed before the backend ignores unknown absence of `parts`; a backend deployed before the browser emits events old reducers ignore.

Rollback disables the real coding model loop before reverting application code. Migration and part rows remain readable. Existing public text is retained with task retention policy. Rollback never reconstructs text from private checkpoint transcripts and never copies tool input into public parts.

## 13. Acceptance Criteria

- assistant public text is visible live and restored from snapshot after reconnect;
- snapshot + replay + live equals uninterrupted replay;
- text events and materialized parts are written under execution-lease fencing;
- stale workers cannot append or complete parts;
- rejected bytes never enter events, outbox payloads, or part content;
- private reasoning and tool input fragments remain content-free;
- 10,000 deltas retain one frame publish behavior;
- full backend coding tests, frontend source tests, Ruff, and TypeScript pass.
