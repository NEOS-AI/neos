# Phase 7 — coding harness reuse + repo skill catalog

## Findings to verify (read-only agents)

1. API ↔ durable loop: `neos/api/handlers/coding_{handlers,ws_handlers,workspace_ws_handlers,admin_handlers}.py` → application services → `CodingRunService` → `CodingLoop.run` (1-step). Confirm routers in `neos/main.py`, event types the FE reducer understands, and any dead routes.
2. Frontend: `web/app/(code)` + `web/features/coding` vs those API contracts (REST snapshot, WS ticket, steer, approvals, workspace tree/file/diff/PTY, sandbox-status). List gaps, not style nits.
3. Skills: `./skills` has ~179 `SKILL.md` and **0** `skill.py`. `discover_skills` requires both, so repo skills never load. Coding `load_skill.v1` only allows `verify`/`commit` from `neos/coding/skills/`.

## Implementation (do not put the coding loop in ChannelGateway or deep_analysis workers)

### A. Extract a vendor-neutral turn harness

New package `neos/coding/harness/` (not inside `loop/durable.py`):

- `ModelTurn` / `collect_model_turn(model, request, *, on_text=None, on_tool_delta=None)`  
  Consumes `CodingModel.stream`, returns text parts + tool calls + `ModelCompleted`.  
  No lease, sandbox, checkpoint, or CodingEvent.
- Durable loop `_advance_one_model_turn` uses this collector and keeps durability/prefetch/compact around it.
- Deep-analysis must be able to import `collect_model_turn` + `create_coding_model` without importing `DurableCodingLoop`. Do **not** rewrite `deep_analysis/llm.py` JSON/budget path in this phase; add a thin documented entrypoint + test that the import graph stays acyclic.

### B. Markdown skill catalog

New `neos/skills/markdown_catalog.py`:

- Scan roots: repo `skills/`, `neos/coding/skills/`, `neos/skills/builtin/`.
- Index `SKILL.md` (and coding `*.md`) by frontmatter `name` + description. No `skill.py` required.
- Path-safe load by name. Do not dump 179 bodies into the system prompt.
- `load_skill.v1` loads any catalog name (keep `verify`/`commit`). Deny path traversal / unknown names.
- `SkillManager.register_builtin_skills` still registers executable builtin `skill.py` skills; also register the markdown catalog so chat/coding can list names.

### C. Tests (TDD)

- harness: stream → turn result; durable loop tests still pass
- catalog: finds `./skills/pdf`; coding verify still loads
- `load_skill.v1` unknown still denied
- import: `neos.workflow.deep_analysis` does not import `DurableCodingLoop` via harness

## Out of scope

- Rewriting deep-analysis to the coding lease/checkpoint loop
- Executing `./skills` Python scripts as sandbox tools
- Push / PR
