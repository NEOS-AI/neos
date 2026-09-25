# Univer Office Runtime — Neos Deep Harness Migration Spec

| Field | Value |
|---|---|
| Date | 2026-09-25 |
| Status | Draft |
| Product | Neos port of DreamNum Univer OSS (v1.0.2) as an Office **runtime** on the existing deep harness |
| Inventory | [../README.md](../README.md) (`00`–`14`) |
| Child specs | [00-harness-and-profile.md](./00-harness-and-profile.md), [01-tools-and-runtime.md](./01-tools-and-runtime.md), [02-skills-safety.md](./02-skills-safety.md), [agents/office-session.md](./agents/office-session.md) |
| Code-grounded process | [MIGRATION_PROCESS.md](./MIGRATION_PROCESS.md) |
| Does not replace | Univer clone inventory. This document decides the **Neos attach**. |

---

## Overview

Univer is not an agent loop. It is an isomorphic Office SDK: plugin + redi DI + COMMAND/MUTATION + Facade (`FUniver`). The agent loop already exists in Neos as the **deep harness**: parent-driven `SubagentRuntime.advance` (no `run_until_done`), used today by coding, deep analysis, designed-graph workflow, and FSI.

This port attaches Univer as a **fifth parent kind** (`ParentKind.UNIVER`) plus four kebab catalog leaves. The parent owns a Node sidecar that runs OSS headless presets. Children inspect and mutate **snapshot JSON** through structured tools. Success is `staged_for_signoff`. A human merges `draft/` into `trunk/`.

```text
Human / other Neos parent
        │
        ▼
neos/univer/loop.py          ParentKind.UNIVER
        │  spawn_agent.v1 handled in-loop (not DurableCodingLoop)
        ▼
SubagentRuntime.advance      univer-reader | univer-formula | univer-writer | univer-critic
        │
        ▼
UniverToolPort ──JSON-RPC──► Node sidecar (preset-sheets-node-core / preset-docs-node-core)
        │                         FUniver.save() / executeCommand / formula wait
        ▼
<session>/draft/*.json       writer jail
<session>/trunk/*.json       parent merge only
```

v0 is Sheets + Docs, OSS Node, flags default **off**, no HTTP/UI until a later asked wave. Slides, Bases, Boards, PDF, Univer Pro, hosted MCP, and `univer-cli` are out of v0.

---

## Background & Motivation

Neos already writes Office-shaped artifacts in FSI via `openpyxl` / `python-pptx` skills (`xlsx-author`, `pptx-author`). Those libraries do not share Univer’s formula engine, COMMAND/MUTATION undo, or isomorphic snapshot. Univer’s own agent products (CLI Worktree, DSH tools, hosted MCP) live in **other GitHub repos** and often pull `@univerjs-pro/*`.

Neos needs the OSS runtime on the loop it already operates:

| Need | Live Neos primitive | Univer piece |
|---|---|---|
| Parent-driven depth-1 children | `neos/subagent/` Approach C | leaves, not a new inner loop |
| Default-deny tools | `SubagentSpec.allowed_tools` ∩ `ToolPort` | structured `univer.*.v1` |
| Isolated writes | FSI writer jail / coding WORKTREE | `draft/` vs `trunk/` snapshot JSON |
| Fold gate | `validate_child_fold` + `full_summary` | reader / formula schemas |
| Markdown procedures | `load_skill.v1` + catalog roots | `skills/univer/` |
| Kill switch | `FsiConfig.enabled` default false | `UniverConfig.enabled` default false |

Do not wrap `https://mcp.univer.ai`. Do not shell out to `univer` CLI (Pro license + trusted JS `execute`). Do not host leaves on DA `Worker` (`search`/`fetch` claims) or `spec=implement` (git worktree + `mkdir`/`rm`).

---

## Goals & Non-Goals

### Goals

1. `ParentKind.UNIVER` tickets on `SubagentRuntime` with four registered leaves.
2. Parent-owned Node sidecar: OSS `preset-sheets-node-core` / `preset-docs-node-core`.
3. Structured tools for inspect, range get/set, allowlisted `executeCommand`, formula wait, save.
4. Exactly one writer leaf. Disk writes only under `draft/`.
5. Skill pack `skills/univer/` loaded only by the Univer parent catalog.
6. Flags default off. Flag-off cancels in-flight children (`cancel_for_parent`).
7. Fold schemas fail-closed. Truncated folds are not schema-validated (FSI review-fix).

### Non-Goals (v0 hard)

- HTTP `/api/v1/univer` or UI until the user asks.
- Univer Pro: collaboration, xlsx/docx exchange, charts, pivot, print, History diff.
- Hosted MCP 30 tools / `@univerjs-pro/mcp*`.
- `univer-cli` daemon, `.univer` SQLite, screenshot, PDF, slide lint.
- Free Facade JavaScript (`execute` as a sandbox).
- Slides Facade (OSS has none), Bases workbench, Boards, PDF units.
- Custom formula functions over RPC (OSS throws: unsafe deserialize).
- FSI `model-builder` rewrite onto Univer this series.
- `neos/subagent` importing `neos.univer`.
- `DurableCodingLoop` / DA orchestrator as the Univer parent.

---

## Proposed Design

### Parent runtime

Add `UNIVER = "univer"` to `ParentKind` together with `metrics._PARENTS` and the next `subagent_runs_parent_kind_check` migration (recipe: `058` workflow, `064` FSI).

`neos/univer/loop.py` loads profile `office-session`, offers compiled parent tools, handles `spawn_agent.v1` by building `SubagentTicket(parent_kind=ParentKind.UNIVER, …)` and looping `advance` until terminal, then `fold` + `validate_child_fold`. Cap live children at 1.

`SandboxMode` on catalog templates **and** spawn copies is `NONE`. `WORKTREE`는 git이라 쓰지 않는다. Parent injects `UniverParentWorkspacePort` so `read_file.v1` / `write_file.v1` hit the session tree (`draft/` jail). Sidecar lifetime is the parent’s.

### Catalog leaves

| Spec | Role | Write disk? | Univer tools |
|---|---|---|---|
| `univer-reader` | Outline + range extract, schema JSON | no | inspect, range_get |
| `univer-formula` | Wait calc, collect ErrorType | no | inspect, formula_wait |
| `univer-writer` | Mutate draft snapshot | **yes** (`draft/**` only) | range_set, execute_command, save, formula_wait |
| `univer-critic` | Re-inspect draft, QC report | no | inspect, range_get |

`can_spawn=False`, `one_shot=True`, `can_approve=False` on all four. Aliases (e.g. `sheet-outline-reader`) register on a session `SpecRegistry` overlay because `advance` re-looks up the catalog.

Stepper must grow a `univer-*` prompt branch when the specs land. Registering them into the explore `else` branch tells the model it may `spawn_agent.v1`.

### Isolation

```
<session>/
  trunk/workbook.json          # accepted IWorkbookData (+ resources)
  trunk/document.json          # accepted IDocumentData
  draft/workbook.json          # writer jail
  draft/document.json
  out/_spec/*.json             # reader/formula/critic folds
```

`merge.v1` is parent-only and human-gated. Writer `write_file.v1` cannot touch `trunk/` or `out/*.xlsx`. v0 does not write xlsx.

### Model

`model.role: powerful`. `pin: null`. Changing the pin must not change tools or schemas.

---

## Key Decisions

| # | Decision |
|---|---|
| KD1 | Univer is a runtime capability. Neos is the loop. |
| KD2 | Fifth parent `ParentKind.UNIVER`. |
| KD3 | Four kebab leaves on `SubagentRuntime`. Depth-1. One writer. |
| KD4 | OSS headless Node presets only. |
| KD5 | Persist Facade `save()` JSON. `draft/` vs `trunk/`. Success = `staged_for_signoff`. 모든 리프 `SandboxMode.NONE`. `WORKTREE`는 git이라 쓰지 않는다. |
| KD6 | Structured `univer.*.v1` tools. No free JS in v0. COMMAND allowlist; never raw MUTATION from the agent. |
| KD7 | Import law: `neos/subagent` ↛ `neos.univer` ↛ DurableCodingLoop / DA. |
| KD8 | `univer.enabled` default false. Child flags require master. |
| KD9 | Skills at `skills/univer/`. Not in coding `default_skill_roots`. |
| KD10 | `output_schema_ref` in YAML; bodies in `neos/univer/schemas.py`. Schema gate only on `exit_reason == "completed"` using `full_summary` if truncated. |
| KD11 | Slides / Bases / Boards / PDF / Pro / hosted MCP / CLI binary out of v0. |
| KD12 | FSI stays on openpyxl this series. |
| KD13 | ParentKind widen = enum + metrics + DB CHECK together. Catalog + stepper prompt together. Overlay SpecRegistry for aliases. |
| KD14 | No HTTP/UI until asked. |
| KD15 | Node missing → tools fail-closed with a coded error. |

---

## API / Interface Changes

| Module | Surface |
|---|---|
| `neos/config/schema.py` | `UniverConfig` |
| `neos/subagent/types.py` | `ParentKind.UNIVER` |
| `neos/subagent/catalog.py` | four specs + aliases via overlay |
| `neos/subagent/prompts.py` | `build_univer_system_prompt_for` |
| `neos/subagent/metrics.py` | `_PARENTS` includes `univer` |
| `neos/univer/loop.py` | parent session |
| `neos/univer/profile.py` | `load_profile` / `compile_leaf_spec` |
| `neos/univer/ports.py` | workspace + sidecar ToolPort |
| `neos/univer/schemas.py` | fold jsonschemas |
| `neos/univer/sidecar.py` | start/stop/JSON-RPC |

Parent tools: `read_file.v1`, `search_text.v1`, `glob_files.v1`, `spawn_agent.v1`, `load_skill.v1`. No Write on the orchestrator.

---

## Data Model Changes

v0 may persist session rows later (`univer_sessions`). Kernel PRs can run without HTTP by keeping state in the session directory + `subagent_runs`. When DDL lands: `parent_kind` CHECK includes `univer`.

Snapshot JSON is Univer’s `IWorkbookData` / `IDocumentData` including `resources[]`. Empty sheet defaults stay SDK: 1000 rows × 20 cols.

---

## Security & Privacy

- Writer jail: `draft/**` only, one-level JSON. Nested `_spec` writes denied (FSI writer lesson).
- Reader inbound (later file import) wraps `<untrusted_document>` with case-insensitive closer rewrite.
- Binding denylist: no publish, send, email, trunk merge, Pro license upload.
- Sidecar binds loopback only.
- `execute_command.v1` allowlist is COMMANDs that go through interceptors. MUTATION ids rejected.
- Authz in OSS is `AuthzIoLocalService` stub. Do not treat it as a production ACL.

---

## Observability

Reuse subagent metrics with `parent_kind=univer`. Sidecar logs: start, RPC method, formula wait duration, save bytes. No telemetry package from `@univerjs/telemetry` unless an app registers it (OSS has interface only).

---

## Risks

| Risk | Mitigation |
|---|---|
| Node/pnpm not on Neos hosts | Fail-closed tool error; sidecar optional at runtime |
| Formula worker vs inline | v0 inline on sidecar main; no custom-fn RPC |
| Snapshot vs xlsx user expectation | Docs + critic; export is a later flag |
| COMMAND ID drift vs Univer upgrades | Allowlist pinned to 1.0.2; CI lists ids |
| Explore prompt leak | Catalog PR must include stepper branch |
| Pro creep | Child spec non-goals; no `@univerjs-pro` in package.json |

---

## Rollout Plan

Normative order: [MIGRATION_PROCESS.md](./MIGRATION_PROCESS.md). Short:

1. Flags + `UniverConfig`
2. ParentKind + metrics + DB CHECK
3. Catalog specs + stepper prompts
4. `neos/univer` ports + sidecar stub
5. schemas + `run_leaf`
6. Skill pack
7. inspect / range tools
8. formula wait
9. writer jail + critic
10. HTTP/UI only when asked

Each kernel step: TDD, one commit, flags stay off.

---

## Open Questions

1. Sidecar: ship a small `neos/univer/js/` package.json pin of `@univerjs/*@1.0.2`, or require operators to provide `UNIVER_SIDECAR_CMD`?
2. Later: should FSI `model-builder` optionally call Univer formula instead of Excel-in-openpyxl?
3. v1 `univer.facade_js.v1` — allowlisted globals only, or never?

---

## References

- Inventory: [../README.md](../README.md)
- FSI harness analog: [../../financial-services/spec/FSI_NEOS_MIGRATION_SPEC.md](../../financial-services/spec/FSI_NEOS_MIGRATION_SPEC.md)
- Subagent runtime: [../../SUBAGENT_RUNTIME_DESIGN.md](../../SUBAGENT_RUNTIME_DESIGN.md)
- Live: `neos/subagent/types.py`, `catalog.py`, `runtime.py`, `neos/fsi/loop.py`, `db/migrations/064_allow_fsi_subagent_parent.sql`
- Univer clone: `/Users/yeonwoosung/Desktop/univer` HEAD `1defaf4` tag `v1.0.2`
