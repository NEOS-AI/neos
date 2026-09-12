# Phase 9a — durable lesson store + owner prompt injection

Hermes fail-open review stays **off**. `learn.coding_lessons` default remains **false**.
Staged lessons never enter the prompt. No `skill.py` generation. No Honcho.

## Why

`InMemoryLessonStore` is process-local. Restart / Celery worker / API process
cannot see each other's lessons.

`neos/coding/runtime.py` hardcodes `owner = None`, so even with the flag on
`approved_texts(...)` never runs. Lessons cannot be owner-scoped.

The real coding loop is built **once per worker**. Baking owner lessons into
`CodingLoopConfig.system` at construction time is the bug. Injection must be
**per task / per model turn**.

## File ownership (this agent only)

| Own | Do not touch |
|---|---|
| `db/migrations/049_add_learned_lessons.sql` | `neos/api/channels/**` |
| `neos/learn/**` | `run_service.steer` / `stop` / lease interrupt |
| `neos/coding/learn_lessons.py` | channel session bind |
| `neos/coding/prompts/builder.py` (only if needed) | Discord/Slack/Telegram adapters |
| `neos/coding/loop/base.py` — add `LoopInput.owner_id: str \| None = None` | new 050 migration |
| `neos/coding/loop/durable.py` — **only** `ModelRequest.system` assembly | |
| `neos/coding/application/run_service.py` — **only** pass `owner_id` into `LoopInput` | |
| `neos/coding/runtime.py` — remove the dead `owner = None` lesson block | |
| `neos/tasks/curate_learned_skills.py` | |
| `tests/learn/**`, `tests/coding/test_learn_lessons.py`, prompt/loop tests you add | |

If you must change `durable.py`, touch only the `ModelRequest(system=...)` path
and a small helper. Do not change cancel / prefetch / compact.

## Persistence

New table `learned_lessons`:

- `lesson_id VARCHAR(64) PRIMARY KEY`
- `namespace VARCHAR(255) NOT NULL`
- `title VARCHAR(255) NOT NULL`
- `body TEXT NOT NULL`
- `status VARCHAR(32) NOT NULL` — `staged` / `approved` / `archived`
- `pinned BOOLEAN NOT NULL DEFAULT FALSE`
- `kind VARCHAR(32) NOT NULL DEFAULT 'fact'`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`
- index `(namespace, status)`

Follow `db/migrations/041_add_coding_sandbox_bindings.sql` style
(`CREATE TABLE IF NOT EXISTS`, no Alembic). Add a contract test like
`tests/coding/test_migration_041_contract.py`.

`LessonStore` protocol may stay sync for `InMemoryLessonStore` (existing
`pytest.mark.no_db` tests must stay green). Add a durable store used in
production (`PostgresLessonStore` + async session factory, same pattern as
`PostgresCodingService`).

`get_lesson_store()` remains the in-memory singleton for unit tests /
`reset_lesson_store()`. Production paths (`stage_coding_lesson`, curator Beat,
prompt injection) must use the durable store when a session factory / DB is
available.

`LessonStore.add` still force-stages when `write_approval` is on.

## Owner prompt injection

1. Delete the `owner = None` / `approved_lessons` block in
   `_prepare_real_coding_loop`. Construction-time `CodingLoopConfig.system`
   is the **static** prompt only (`approved_lessons=()`).
2. `LoopInput` gains `owner_id: str | None = None`.
3. `CodingRunService.advance_one_safe_point` loads the task and passes
   `owner_id=task.owner_id` into `LoopInput`.
4. In `DurableCodingLoop._advance_one_model_turn`, build the request system
   as: static `self._config.system` + optional `## Lessons` from
   `approved_texts(store, namespace(owner_id))` **only when**
   `settings.config.learn.coding_lessons` is true **and** `input.owner_id`
   is a non-empty string.
5. Empty owner, missing task, or flag off → no `## Lessons` section.
6. Staged / archived bodies must not appear. Only `LessonStatus.APPROVED`.
7. Do not invent token counts. Do not put staged text into the static config.

Helper should live in `neos/learn/` or `neos/coding/learn_lessons.py`
(e.g. `approved_lesson_texts(owner_id) -> tuple[str, ...]`).

## Policy (unchanged)

- `learn.coding_lessons` default **false**
- `learn.write_approval` default **true**
- `namespace(owner_id)` → `owner:{id}`
- Fail closed. No owner → no injection.
- Bundled skill names stay protected in the curator.

## Tests (TDD)

Write the failing test first, then implement.

Required cases:

1. Durable store: add in one store instance, read from a **new** instance
   sharing the same backend (in-memory fake of the durable adapter is OK if
   the adapter is not process-global; SQL contract test for the migration).
2. Flag off → `stage_coding_lesson` still no-op; no prompt section.
3. Flag on + staged → not in `approved_texts` / not in model system.
4. Flag on + approved + real `owner_id` on `LoopInput` → `## Lessons` in the
   `ModelRequest.system` for that turn.
5. Flag on + `owner_id=None` → no `## Lessons`.
6. Owner A approved lesson must not appear on owner B's turn.
7. Existing `tests/learn/**` and `tests/coding/test_learn_lessons.py` stay green.

Use `pytest.mark.no_db` unless the test truly needs Postgres.

## Out of scope

Channel bind, `/stop`, Celery revoke, Discord/Block Kit, enabling
`coding_lessons` by default, LLM curator, writing into `neos/skills/builtin`.
