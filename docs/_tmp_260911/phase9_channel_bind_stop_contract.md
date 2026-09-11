# Phase 9b — durable channel session→task bind + real `/stop`

Do not put the coding loop into `ChannelGateway`. Do not replace the gateway.
Coding stays on `CodingTaskService` / `CodingRunService` (NEOS_CODING.md §3.3).

## Why

`ChannelGateway._task_by_session` is an in-process dict. A second API replica,
a process restart, or a different worker cannot resolve `/stop` / `/status`.

`RuntimeChannelCoding.stop_task` calls `coding_run_service.stop()`, which uses
`InProcessRunInterrupter`. That only `task.cancel()`s asyncio tasks **bound in
the same process**. The coding loop runs in Celery. Channel `/stop` from the
API process is therefore a no-op on a live run.

`CodingRunService.steer(..., mode=INTERRUPT_NOW)` already queues a durable
steering row, but if the worker holds the execution lease it **raises
`RunAlreadyLeased`**. That is the common case for a running task.

## File ownership (this agent only)

| Own | Do not touch |
|---|---|
| `db/migrations/050_add_channel_coding_bindings.sql` | `neos/learn/**` |
| `neos/api/channels/gateway.py` | `neos/coding/learn_lessons.py` |
| `neos/api/channels/coding_bridge.py` | prompt builder / `## Lessons` |
| `neos/api/channels/session_bind.py` (new) | `049_add_learned_lessons.sql` |
| `neos/coding/application/run_service.py` — `steer` / `stop` / interrupt-when-busy | `LoopInput.owner_id` (leave default `None`) |
| `neos/coding/loop/durable.py` — **only** pending-interrupt poll + abort | `ModelRequest.system` / lessons |
| `neos/coding/repositories/run_repository.py` — pending interrupt query if needed | |
| `tests/api/channels/**` plus run_service / loop tests you add | |

## Durable bind

Table `channel_coding_bindings`:

- `session_id VARCHAR(255) PRIMARY KEY`
- `task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE`
- `owner_id VARCHAR(255) NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`
- index on `task_id`

`/code` upserts `(session_id → task_id, owner_id)`.
`/stop` `/status` approve/deny load the bound task. Missing →
`"No coding task in this thread."`

`ChannelGateway` must take an injectable bind store (protocol). Tests keep
using an in-memory implementation so `pytest.mark.no_db` stays valid.
Production default is the Postgres store (session factory like other coding
repos).

A **new** `ChannelGateway` instance must see binds written by a previous
instance when they share the store. That is the restart/replica contract.

Do not rewrite session keys. v2 keys stay as-is.

## Real `/stop` across Celery

1. `RuntimeChannelCoding.stop_task` must go through durable cancel, not
   in-process-only `InProcessRunInterrupter`.
   Preferred: `CodingRunService.steer(task_id, owner_id, instruction="stop",
   mode=SteeringMode.INTERRUPT_NOW)` (owner-checked) or a dedicated
   `request_stop` that shares that path.
2. `steer(INTERRUPT_NOW)` **must not fail** when the worker already holds
   the lease. Queue the steering row and return it. The live worker is
   responsible for applying it. `RunAlreadyLeased` is the wrong signal for
   `/stop`.
3. Worker applies a pending `INTERRUPT_NOW` at the next safe point
   (`advance_one_safe_point` / `on_safe_point`). Synthesize aborted
   tool_results and persist the abort checkpoint (existing cancel path).
4. Mid-turn: `DurableCodingLoop` must notice a pending interrupt during
   `iter_model_turn` (cheap poll — e.g. `has_pending_interrupt(task_id)` on
   the run repository) and take the same abort path as `CancelledError`.
   Do **not** `celery.control.revoke(..., terminate=True)` — that skips the
   abort checkpoint.
5. `stop()` may remain as a convenience wrapper, but it must persist the
   request even when this process has no bound asyncio.Task.
6. After `/stop`, `/status` still resolves the same bound `task_id` and
   reports the durable status (cancelled / interrupting / …).

Keep existing HTTP `POST /tasks/{id}/steer` behavior for `safe_point`.
Only change the lease-busy branch of `INTERRUPT_NOW` so stop is accepted.

## Tests (TDD)

Write the failing test first, then implement.

Required cases:

1. Bind written by gateway A is visible to gateway B with the same store.
2. `/stop` with no bind → `"No coding task in this thread."`
3. `/code` then new gateway `/stop` uses the persisted `task_id`.
4. `steer(INTERRUPT_NOW)` while a lease is held **queues** and does not
   raise `RunAlreadyLeased`.
5. Worker / loop: pending `INTERRUPT_NOW` aborts the in-flight turn and
   writes the aborted checkpoint (fake model + fake repo is enough).
6. Existing `tests/api/channels/test_gateway_router.py` stays green
   (inject in-memory bind; FakeCoding still works).
7. Channel `/stop` does not call `execute_workflow`.

## Out of scope

Lesson store, prompt injection, Block Kit, Discord auto-thread, pairing,
media, putting the coding loop inside the gateway, enabling
`channels.coding_invoke` by default.
