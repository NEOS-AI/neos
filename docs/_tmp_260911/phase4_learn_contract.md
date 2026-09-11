# Phase 4 self-improve contract

Hermes fail-open review is **not** the default. Write-approval ON. No `skill.py` generation. No Honcho.

## File ownership

| Owner | Files |
|---|---|
| Core | `neos/learn/**`, `neos/config/schema.py` LearnConfig, `config/neos.default.yaml`, `tests/learn/**` |
| Memory wire | `neos/memory/manager.py` (`learn` filter/cap), `neos/api/services/vote_service.py`, `neos/workflow/graph.py` `_save_episode_memory` only |
| Coding lessons | `neos/coding/learn_lessons.py` (new), `neos/coding/application/run_service.py` (hook only), `neos/coding/prompts/builder.py`, `neos/coding/runtime.py` (approved lessons into prompt), `tests/coding/prompts/test_builder.py`, `tests/coding/test_learn_lessons.py` |
| Search + Beat | `neos/learn/session_search.py`, `neos/tasks/curate_learned_skills.py`, `neos/workflow/celery_app.py` beat entry only, `tests/learn/test_session_search.py`, beat schedule test |

## Policy (`LearnConfig`, defaults)

- `write_approval: true`
- `coding_lessons: false` (opt-in; staged even when on)
- `curator: true`
- `stale_days: 30`, `archive_days: 90`
- `max_knowledge_chars: 400`

`is_imperative(text)` rejects leading Always/Never/You must/Do not/Don't (case-insensitive).
`namespace(owner_id, workspace_id=None)` → `owner:{id}` or `owner:{id}:ws:{ws}`.
Bundled skill names (15 builtin) are protected: curator must not archive them.

## Lessons

Staged vs approved. `LessonStore.add` always starts `staged` unless `write_approval` is false **and** caller is explicit (default still staged).
`approved_texts(namespace)` returns only approved bodies.
No executable code in lesson body. Extractors write markdown facts only.

Coding extractor (deterministic, no LLM): if outcome is failure or events contain `tool.denied` / `tool_outcome_unknown` / test/lint failure text, write a short lesson. Else None.

Research procedure: class-level 60-char description + markdown body. Never `skill.py`.

## Prompt

`build_coding_system_prompt` may add `## Lessons` **only** from `env.approved_lessons`. Staged must not appear.

## Session search

`search_user_sessions(user_id, query, limit=5)` requires non-empty `user_id` (ValueError). Uses existing similarity search with that user_id. No LLM summary layer.

## Beat

`neos.tasks.curate_learned_skills` every 86400s. Prune/archive only. LLM consolidate off.

## Out of scope

Honcho, pets, auto-deploy to `neos/skills/builtin`, inline shell in skills, LLM curator consolidate.
