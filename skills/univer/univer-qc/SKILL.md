---
name: univer-qc
description: Critic checks on a Univer draft JSON snapshot. Use to re-inspect formula errors, null cells versus style-only, merges, and data validation. Read-only. Not for writing drafts or merging trunk.
---

# Univer QC (critic)

Critic only. No write tools. Re-read the draft with `univer.inspect.v1` and re-aggregate formula errors.

## Null vs style-only

`isNullCell`: a cell with no `v` / `f` / `si` / `p` is empty. **A style-only cell is also a null cell.** Reporting “there is a background color, so there is a value” is a bug.

## Formula errors

Use `getAllFormulaError()` and the ErrorType list. A value read before dirty wait is stale, not an error. Check inspect metadata that wait finished first.

## Merge

`getMergeData` / `isMerged` / `isPartOfMerge`. Only the top-left of a merge holds a value; the rest looking empty can be normal.

## Validation

Sheets data validation exists in OSS. `FWorkbook.save()` resources include DV plugin data. Do not invent Docs data validation.

## Display values

`getValue` may be an interceptor-composed value (`CELL_CONTENT`). The source field is `ICellData.v`. Report both separately.

## Forbidden

Writing the draft, merging trunk, xlsx export, mail, and upload.
