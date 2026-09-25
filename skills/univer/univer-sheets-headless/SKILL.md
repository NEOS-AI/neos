---
name: univer-sheets-headless
description: Headless Univer Sheets via Facade FWorkbook/FRange. Use to create or mutate a workbook JSON snapshot with setValue/setFormula, wait for formula application, and FWorkbook.save(). Not for Pro xlsx I/O, charts, pivot, CLI worktrees, or Slides.
---

# Univer Sheets (headless)

Writer leaf loads this skill. Reader does not (`skill_allowlist: []`).

## Boot

Use `preset-sheets-node-core`. `createUniver` returns `{ univer, univerAPI }`. Side-effect imports such as `import '@univerjs/sheets/facade'` must run before `createUniver`; without them `createWorkbook` is `undefined`. UI facade is not on the Node core preset.

## Handles

```
univerAPI.createWorkbook(data)
  → FWorkbook.getActiveSheet()
  → FWorksheet.getRange('A1')
  → FRange
```

## Write

`FRange.setValue` / `setValues` / `setFormula`. Internally this is `sheet.command.set-range-values` (`SetRangeValuesCommand`). Do not call MUTATION ids directly — that skips undo, interceptors, and permission hooks.

## Save

Round-trip and agent verification use **`FWorkbook.save()`**. That snapshot includes plugin `resources` (data validation, conditional formatting, filter). `Workbook.getSnapshot()` omits resources; do not use it to verify agent work.

## Formula wait

`setFormula` only marks cells dirty. Before reading cell `v`, `await univerAPI.getFormula().onCalculationResultApplied()`. Force a recalc with `executeCalculation()`.

## Cell contract

`ICellData` may hold `v` / `f` / `p` / `s` together. `undefined` keeps a key; `null` deletes it. An empty sheet defaults to 1000 rows × 20 columns, row height 24, column width 88.

## Permissions

OSS `AuthzIoLocalService` is a local stub, not a remote ACL. Do not teach that “the permission server refused.”

## Forbidden

xlsx import/export, charts, pivot, screenshot Facade, `mcp.univer.ai`, and Pro license registration.
