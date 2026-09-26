---
name: univer-sheets-headless
description: Headless Univer Sheets via structured univer.*.v1 tools on the Python InMemorySidecar. Use to inspect, set A1 values/formulas, run allowlisted COMMANDs, wait for calculation, and save draft/workbook.json. Not for Pro xlsx I/O, charts, pivot, CLI worktrees, or Slides.
---

# Univer Sheets (headless)

Writer leaf loads this skill. Reader does not (`skill_allowlist: []`).

## Runtime

Live engine is Python `InMemorySidecar`. Node `@univerjs` presets are deferred. Parent owns the sidecar; the leaf does not start Node.

Call structured tools:

- `univer.inspect.v1` — unit outline, optional values, formula errors
- `univer.range_get.v1` — A1 cells (`v` / `t` / `f`)
- `univer.range_set.v1` — set A1 `value` or `formula` (top-left of a range)
- `univer.execute_command.v1` — allowlisted sheet COMMANDs
- `univer.formula_wait.v1` — apply dirty formulas in sidecar memory
- `univer.save.v1` — write `draft/workbook.json` only

## Write

Prefer `univer.range_set.v1` with `a1` plus `value` or `formula`. Allowlisted COMMANDs go through `univer.execute_command.v1`. Do not call MUTATION ids (`*.mutation.*` / `*.operation.*`) — that is `mutation_forbidden`.

Sheet COMMANDs this wave:

- `sheet.command.set-range-values`
- `sheet.command.insert-row` / `insert-col` / `remove-row` / `remove-col`
- `sheet.command.add-worksheet-merge`
- `sheet.command.sort-range`
- `sheet.command.addDataValidation`
- `sheet.command.add-conditional-rule`
- `sheet.command.add-table`

Doc COMMANDs on a sheet unit return `unit_kind_mismatch`.

## Save

`univer.save.v1` writes `draft/workbook.json`. Other paths are `path_denied`. Snapshot JSON is an IWorkbookData-shaped subset (one sheet, `appVersion` `1.0.2`). If formulas are dirty, save and inspect-with-values fail with `formula_dirty`. Wait first.

## Formula wait

`range_set` / formula writes only mark cells dirty. Before reading computed `v`, call `univer.formula_wait.v1`. Supported this wave: `SUM`, `IF`, arithmetic. Other function names evaluate to `#NAME?`.

## Cell contract

`ICellData` may hold `v` / `f` / `p` / `s` together. `undefined` keeps a key; `null` deletes it. An empty sheet defaults to 1000 rows × 20 columns, row height 24, column width 88.

## Permissions

OSS `AuthzIoLocalService` is a local stub, not a remote ACL. Do not teach that “the permission server refused.”

## Forbidden

xlsx import/export, charts, pivot, screenshot, `mcp.univer.ai`, Pro license registration, and merging trunk.
