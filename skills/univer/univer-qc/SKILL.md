---
name: univer-qc
description: Critic checks on a Univer draft JSON snapshot via read-only univer.inspect.v1 and univer.range_get.v1. Use to re-inspect formula errors, null cells versus style-only, and merges. Read-only. Not for writing drafts or merging trunk.
---

# Univer QC (critic)

Critic only. No write tools. No trunk merge. Live runtime is Python `InMemorySidecar`. Re-read the draft with `univer.inspect.v1` and `univer.range_get.v1`. Do not call `univer.range_set.v1`, `univer.execute_command.v1`, or `univer.save.v1`.

## Null vs style-only

A cell with no `v` / `f` / `si` / `p` is empty. **A style-only cell is also a null cell.** Reporting “there is a background color, so there is a value” is a bug.

## Formula errors

Re-aggregate `formula_errors` from `univer.inspect.v1`. A value read before dirty wait is stale, not an error. Check inspect metadata that wait finished first (`formula_dirty` must be clear).

## Merge

Inspect `mergeData`. Only the top-left of a merge holds a value; the rest looking empty can be normal.

## Validation

Sheets data validation may appear on snapshot `resources`. Do not invent Docs data validation.

## Forbidden

Writing the draft, merging trunk, xlsx export, mail, and upload.
