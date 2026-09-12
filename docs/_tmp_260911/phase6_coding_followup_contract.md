# Remaining coding-loop / coding-tool contract

No coordinator/team. No curl via execute.v1. No Claude prompt paste.

## File ownership

| Owner | Files |
|---|---|
| Core (landed) | this contract, `SearchMatch` extra fields, `SandboxSession.glob_files`, `CodingModelConfig.web_fetch_hosts` |
| Tools | `registry.py`, `executor.py` (new tools + search schema), `observability.py` names, `phases.py` hide spawn in explore/verify, `tests/coding/tools/*` |
| Sandbox | `sandbox/memory.py`, `sandbox/docker.py` (search context + glob helper), `tests/coding/sandbox/*` if present |
| Loop | `loop/anthropic.py`, `tests/coding/loop/test_anthropic_loop.py` |

## Grep / Glob
- `search_text.v1` adds optional `before`/`after` (0–20 lines), keep `query/paths/regex/limit`.
- `glob_files.v1` READ_ONLY: `{pattern: str, limit?: int 1–500 default 100}`. Workspace-relative, no `..`.
- `SearchMatch` may include `before`/`after` tuples (default empty).
- Prefer these over `execute rg/find`.

## WebFetch
- `web_fetch.v1` READ_ONLY: `{url: str}`. GET only. Host must be in `coding_model.web_fetch_hosts` (empty = deny all).
- http/https only. No file/redirect-to-private-IP required for first slice: deny non-http(s), deny if host not allowlisted.
- Timeout 15s, body cap 200KiB, return markdown/text preview.
- `execute` curl/wget stays denied.

## Deferred ToolSearch
- If `definitions()` full set > 20 (or `deferred_tools_threshold`), expose core tools + `search_tools.v1` only.
- Core always: read/search/glob/list/stat/edit/write/execute/todo/set_phase/ask/load_skill/search_tools.
- `search_tools.v1` `{query: str}` returns matching deferred tool name+description+schema in `entries`. Loop/runtime may pass `revealed` later; first slice: search result is the schema dump so the model can call the tool next turn **if** definitions also reveal it.
- Simpler first slice: `search_tools` returns schemas; `definitions(revealed=names)` includes those names. Loop state `revealed_tools: frozenset`. On successful search_tools, merge names into state.

## Stream-during-RO
- In `_advance_one_model_turn`, when a `ToolCallCompleted` is READ_ONLY and allowed in phase, start `asyncio.create_task` execute (no mutate).
- After the stream, await tasks. Pass results into `_advance_one_tool` so RO execute is not repeated.
- Crash: RO reclaim still reruns. Prefetch is same-invocation only.

## spawn_agent.v1
- Input `{prompt: str, max_turns?: int 1–8 default 4}`.
- READ_ONLY. Hidden in explore/verify (no recursion).
- Loop intercepts: nested explore-only toolset, same sandbox session, no write/execute/spawn. Return last assistant text or "no output".
- Not a separate Celery task. Same process, bounded turns.

## LLM compact
- After deterministic `_compact`, if still over budget (or `force` after 413) and model available: one no-tool model turn summarizing the **unprotected prefix** (not first user, not active tool pair) into a short user message.
- On failure, keep deterministic compact. One attempt (`llm_compact_attempts` on state, max 1).

## Out of scope
coordinator, WebFetch SSRF full private-IP scan (allowlist only), Discord UX, stream-during-mutate.
