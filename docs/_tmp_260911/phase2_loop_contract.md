# Phase 2 coding-loop contract

Do not copy Claude Code. Durable 1-step machine stays. No while(true).

## File ownership

| Owner | Files |
|---|---|
| Orchestrator (landed / landing) | `neos/coding/tools/orchestrator.py`, `tests/coding/tools/test_orchestrator.py` |
| Hooks (landed / landing) | `neos/coding/hooks.py`, `tests/coding/test_hooks.py` |
| Approvals agent | `neos/coding/domain/approvals.py`, `tests/coding/domain/test_approvals.py` only |
| Todo agent | `neos/coding/tools/registry.py`, `neos/coding/tools/executor.py`, `neos/coding/sandbox/observability.py` (`todo_write.v1` in `_CODING_TOOLS`), `tests/coding/tools/test_registry.py`, `tests/coding/tools/test_executor.py` |
| Loop agent | `neos/coding/loop/anthropic.py`, `neos/coding/application/run_service.py` (`InProcessRunInterrupter` only + bind in `advance_one_safe_point`), `neos/coding/repositories/run_repository.py` (`apply_steering_at_safe_point` pending_instruction), `tests/coding/fakes.py` (same pending_instruction write), `tests/coding/loop/test_anthropic_loop.py`, related slice tests if they break |

## Approvals

`approval_display_summary` keeps existing keys and may add `warnings: list[str]`.

Detect from `execute.v1` argv joined (no shell join beyond space):

- `rm` + `-r`/`-rf`/`-fr` → `destructive_recursive_delete`
- `git reset --hard` → `destructive_git_reset`
- `git push` + `--force`/`-f` → `destructive_force_push`

Do **not** auto-allow pytest/ruff. Do not put argv values other than the executable name into the summary. Warnings are codes, not the raw args.

Existing tests that compare summary == `{executable, argument_count}` must allow extra `warnings` key (empty list or omit when none — prefer omit when empty).

## todo_write.v1

Registry, immediately before `execute.v1`:

```
todos: list[{id?: str, content: str min 1, status: pending|in_progress|completed}]
min_length 1
```

Risk: `READ_ONLY` (no approval). Description: use for 3+ step work; do not use for a one-line edit.

Executor: no sandbox I/O. Return `ToolResult.ok` and put the todos in `entries` as mappings.

Do not change edit/write/read behavior.

Loop agent (not todo agent) persists `loop_state.todos` from a successful todo_write.

## Orchestrator

`partition_leading_readonly(calls, *, max_batch=10) -> tuple[batch, rest]`

- Leading consecutive `ToolRisk.READ_ONLY` up to max_batch
- First WORKSPACE_WRITE/COMMAND starts `rest` (that call is first of rest)
- Empty in → empty batch

## Hooks

`CodingHookPort` / `NullCodingHooks`: `pre_tool`, `post_tool`, `stop`, `compact` — all no-op async. Loop calls them. **Do not call `stop` on model/API errors.**

## Loop (anthropic + interrupter + steer persist)

### Cancel + synthetic results
- `InProcessRunInterrupter` keeps `run_id -> asyncio.Task`. `bind`/`unbind`. `interrupt` cancels the task. If no task, `process_stopped=True` (same as today for tests).
- `advance_one_safe_point` binds `asyncio.current_task()` around the stream, unbinds in `finally`.
- On `CancelledError` in `_advance_one_tool` / model turn: for every remaining `pending_tool_calls[pending_tool_index:]` without a result, append `ToolResultContent(id, "error", {reason_code: "aborted"})`. Checkpoint. Re-raise.
- Resume must see paired tool_use/tool_result ids.

### Batch RO
- From `pending_tool_index`, validate the remaining calls, `partition_leading_readonly`.
- If batch size > 1: claim all, `asyncio.gather` execute (each gets `known_reads`), complete each, one checkpoint with all results applied in order via repeated `_after_result`.
- Mutate stays one-at-a-time (current path).
- Max batch 10.

### Steer
- `apply_steering_at_safe_point` (postgres + in-memory fake) must set `loop_state["pending_instruction"] = request.instruction` (today it writes `None`).
- `_restore`: if `pending_instruction` is a non-empty string, append `CanonicalMessage("user", (TextContent(instruction),))` and clear it in the in-memory state.
- `_dump_state`: write `pending_instruction` from state (None after consume).
- Do not mix steer text into a tool_result.

### Compact
Replace hash-drop-everything when over budget:
1. Shrink **old** `ToolResultContent` bodies to `{compacted: true, sha256}` but keep `tool_call_id` + `status`.
2. Never drop or rewrite ids of the **active** tail: last assistant message that contains `ToolUseContent` and the tool messages after it.
3. If still over: drop oldest non-active messages, prepend one user notice `Prior transcript compacted; kept tool pairs.`
4. If still over: existing `transcript_budget_exceeded`.
5. No LLM summary turn.

### Hooks wire
Construct `NullCodingHooks` on the loop (optional ctor arg). `pre_tool` before execute, `post_tool` after, `compact` after `_compact` if the transcript changed, `stop` only on clean `end_turn` completion — never on `CodingModelError` / `CodingLoopFailure`.

### todos in loop_state
On successful `todo_write.v1`, set `state.todos` from the input list (tuple of mappings). Dump/restore `todos`.

## Out of scope
LLM compact, stream-during-tool, coordinator, `/code`, channel session v2, Claude prompt paste.
